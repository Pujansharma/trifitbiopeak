import hashlib
import json
from datetime import UTC, date, datetime, time
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.db.models import Avg, Count, Max, Min, Sum
from django.utils import timezone

from wearables.models import (
    HealthDailySummary,
    HealthObservation,
    RookHealthDocument,
    RookMemberIdentity,
    RookWebhookReceipt,
    WearableConnection,
)
from wearables.services.connections import (
    get_or_create_connection,
    record_connection_event,
)
from wearables.services.job_queue import enqueue_health_job
from wearables.services.lifecycle import can_ingest_source, source_permission_for_domain
from wearables.services.metrics import (
    ExtractedMetric,
    extract_metric_values,
    is_v1_display_metric,
    structure_represents_workout,
)
from wearables.services.provenance import extract_provenance
from wearables.services.signature import rook_metadata_datetime_string
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    DocumentStatus,
    HealthDomain,
    HealthJobType,
    HistoricalImportStatus,
    PermissionStatus,
    WearableSource,
)

DOCUMENT_TIME_FIELDS = [
    "datetime",
    "date",
    "datetime_string",
    "date_time",
    "start_datetime_string",
    "start_date_time",
    "summary_date_string",
    "last_updated_datetime_string",
    "sleep_date_string",
    "sleep_start_datetime_string",
    "activity_start_datetime_string",
    "activity_end_datetime_string",
    "period_start_date_string",
]


def json_digest(value: Any) -> str:
    serialized = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def find_first_value(node: Any, field_names: set[str]) -> Any:
    if isinstance(node, dict):
        for field_name in field_names:
            if field_name in node and node[field_name] is not None:
                return node[field_name]
        for value in node.values():
            found = find_first_value(value, field_names)
            if found is not None:
                return found
    if isinstance(node, list):
        for value in node:
            found = find_first_value(value, field_names)
            if found is not None:
                return found
    return None


def document_datetime_value(payload: dict) -> Any:
    # ROOK v2's canonical instant lives in nested metadata. Prefer it so
    # corrections and on-demand recovery documents share the same identity.
    return rook_metadata_datetime_string(payload) or find_first_value(
        payload, set(DOCUMENT_TIME_FIELDS)
    )


def parse_document_datetime(payload: dict) -> datetime:
    value = document_datetime_value(payload)
    if not isinstance(value, str) or not value.strip():
        raise ValueError("ROOK document is missing a datetime.")
    normalized = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed_date = date.fromisoformat(normalized[:10])
        except ValueError as error:
            raise ValueError("ROOK document datetime is invalid.") from error
        parsed = datetime.combine(parsed_date, time.min)
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, UTC)
    return parsed.astimezone(UTC)


def document_structure(payload: dict) -> str:
    value = payload.get("data_structure") or payload.get("type") or "unknown"
    return str(value)[:128]


def document_version(payload: dict) -> int:
    value = payload.get("document_version") or payload.get("version") or 1
    try:
        version = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("ROOK document version is invalid.") from error
    if version < 1:
        raise ValueError("ROOK document version must be positive.")
    return version


def document_identity_digest(
    *,
    customer_profile_id,
    data_structure: str,
    observed_at: datetime,
    payload: dict,
) -> str:
    # ROOK's canonical correction key: same member, structure and UTC instant.
    # Provider event IDs are intentionally excluded so a higher document_version
    # can supersede the same observation without creating a duplicate document.
    return json_digest([str(customer_profile_id), data_structure, observed_at.isoformat()])


def receipt_payload(payload: dict) -> dict:
    return {
        "client_uuid": payload.get("client_uuid"),
        "user_id": payload.get("user_id"),
        "datetime": document_datetime_value(payload),
        "data_structure": payload.get("data_structure") or payload.get("type"),
        "document_version": payload.get("document_version") or payload.get("version"),
    }


def create_receipt(
    *,
    receipt_key: str,
    payload: dict,
    signature_valid: bool,
    status: str,
    reason: str = "",
    document: RookHealthDocument | None = None,
) -> tuple[RookWebhookReceipt, bool]:
    receipt, created = RookWebhookReceipt.objects.get_or_create(
        receipt_key=receipt_key,
        defaults={
            "rook_user_id": str(payload.get("user_id") or "")[:50],
            "document": document,
            "signature_valid": signature_valid,
            "status": status,
            "reason": reason[:128],
            "payload": receipt_payload(payload),
            "received_at": timezone.now(),
        },
    )
    # Rejected source/consent deliveries may be resubmitted after an explicit
    # reauthorization. A past rejection must not become a permanent gap.
    if not created and receipt.status == DocumentStatus.REJECTED and status == DocumentStatus.QUEUED:
        receipt.document = document
        receipt.signature_valid = signature_valid
        receipt.status = status
        receipt.reason = reason[:128]
        receipt.received_at = timezone.now()
        receipt.save(update_fields=["document", "signature_valid", "status", "reason", "received_at", "updated_at"])
    return receipt, created


def wearable_source_values() -> set[str]:
    return {choice.value for choice in WearableSource}


def acceptable_source_connections(*, identity, provenance: dict) -> tuple[list, str]:
    """Reject deliveries from unlinked, disconnected or unpermitted sources.

    ROOK may return a provider-resolved document with multiple source labels.
    To guarantee a revoked source cannot contribute, every identified source
    must remain authorized. An unattributed ROOK document is only accepted
    when one eligible connection exists (never guess between two providers).
    Caller locks the identity row before applying this policy.
    """
    available = list(WearableConnection.objects.select_for_update().filter(
        customer_profile=identity.customer_profile,
    ))
    sources = set(provenance["data_sources"]) - {"unspecified"}
    if sources:
        matches = [connection for connection in available if connection.data_source in sources]
        if len(matches) != len(sources):
            return [], "unlinked_source"
        if not all(can_ingest_source(connection) for connection in matches):
            return [], "inactive_or_unpermitted_source"
        return matches, ""
    matches = [connection for connection in available if can_ingest_source(connection)]
    if len(matches) != 1:
        return [], "ambiguous_or_unauthorized_source"
    return matches, ""


def promote_matching_connections(
    *, identity: RookMemberIdentity,
    connections: list[WearableConnection],
    observed_at: datetime, received_at: datetime,
) -> None:
    for connection in connections:
        if not can_ingest_source(connection):
            continue
        previous_status = connection.status
        connection.last_webhook_received_at = received_at
        connection.last_successful_sync = received_at
        connection.connected_at = connection.connected_at or received_at
        connection.available_from = min(
            filter(None, [connection.available_from, observed_at]),
            default=observed_at,
        )
        connection.available_to = max(
            filter(None, [connection.available_to, observed_at]),
            default=observed_at,
        )
        # Incoming live data must not falsely claim that historical import or
        # a reconnect gap-fill has finished. Permission-limited sources remain
        # partial; provider transport errors can recover on successful data.
        if connection.status in {ConnectionStatus.IDLE, ConnectionStatus.PROVIDER_ERROR}:
            if connection.import_status == HistoricalImportStatus.RUNNING:
                connection.status = ConnectionStatus.IMPORTING
            elif connection.import_status == HistoricalImportStatus.PARTIAL or connection.permission_status == PermissionStatus.LIMITED:
                connection.status = ConnectionStatus.PARTIAL
            else:
                connection.status = ConnectionStatus.ACTIVE
        if previous_status == ConnectionStatus.PROVIDER_ERROR:
            connection.last_error_code = ""
            connection.last_error_detail = ""
        connection.save()
        if previous_status != connection.status:
            record_connection_event(
                connection, event_type="webhook_data_received",
                previous_status=previous_status,
                detail="Authorized source delivered a verified ROOK document.",
            )


@transaction.atomic
def ingest_rook_document(payload: dict, *, signature_valid: bool,
                         enqueue_normalization: bool = True) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("ROOK webhook document must be an object.")
    content_hash = json_digest(payload)
    receipt_key = json_digest([content_hash, payload.get("user_id")])
    existing_receipt = RookWebhookReceipt.objects.filter(
        receipt_key=receipt_key
    ).first()
    if existing_receipt is not None:
        rejected_document = (
            existing_receipt.document_id
            and existing_receipt.document.status == DocumentStatus.REJECTED
        )
        if existing_receipt.status != DocumentStatus.REJECTED and not rejected_document:
            return {
                "accepted": True,
                "duplicate": True,
                "reason": existing_receipt.reason or "exact_replay",
            }
        # A rejected delivery is still subject to all current source and
        # consent checks below; never blindly trust an old receipt.

    rook_user_id = payload.get("user_id")
    if not isinstance(rook_user_id, str) or not rook_user_id:
        create_receipt(
            receipt_key=receipt_key,
            payload=payload,
            signature_valid=signature_valid,
            status=DocumentStatus.REJECTED,
            reason="missing_user_id",
        )
        raise ValueError("ROOK document is missing user_id.")
    identity = (
        RookMemberIdentity.objects.select_for_update()
        .select_related("customer_profile")
        .filter(rook_user_id=rook_user_id)
        .first()
    )
    if identity is None:
        create_receipt(
            receipt_key=receipt_key,
            payload=payload,
            signature_valid=signature_valid,
            status=DocumentStatus.REJECTED,
            reason="unknown_user",
        )
        return {"accepted": True, "skipped": True, "reason": "unknown_user"}

    # DPDP: a delayed/replayed webhook must not create new observations after
    # the member has withdrawn all wearable-ingestion consent.
    from wearables.services.consent import has_active_wearable_consent
    if not has_active_wearable_consent(identity.customer_profile):
        create_receipt(
            receipt_key=receipt_key, payload=payload,
            signature_valid=signature_valid, status=DocumentStatus.REJECTED,
            reason="consent_revoked",
        )
        return {"accepted": True, "skipped": True, "reason": "consent_revoked"}

    observed_at = parse_document_datetime(payload)
    data_structure = document_structure(payload)
    version = document_version(payload)
    provenance = extract_provenance(payload)
    permitted_connections, rejection = acceptable_source_connections(
        identity=identity, provenance=provenance,
    )
    if rejection:
        create_receipt(
            receipt_key=receipt_key, payload=payload,
            signature_valid=signature_valid, status=DocumentStatus.REJECTED,
            reason=rejection,
        )
        return {"accepted": True, "skipped": True, "reason": rejection}
    if provenance["data_sources"] == ["unspecified"]:
        # Attribution is unambiguous only for a single live connection.
        provenance["data_sources"] = [permitted_connections[0].data_source]
        provenance["source_label"] = permitted_connections[0].data_source
    document_identity = document_identity_digest(
        customer_profile_id=identity.customer_profile_id,
        data_structure=data_structure,
        observed_at=observed_at,
        payload=payload,
    )
    document = (
        RookHealthDocument.objects.select_for_update()
        .filter(document_identity=document_identity)
        .first()
    )
    if document is not None and version < document.document_version:
        create_receipt(
            receipt_key=receipt_key,
            payload=payload,
            signature_valid=signature_valid,
            status=DocumentStatus.REJECTED,
            reason="lower_document_version",
            document=document,
        )
        return {"accepted": True, "skipped": True, "reason": "lower_document_version"}
    if (document is not None and version == document.document_version
            and document.status != DocumentStatus.REJECTED):
        reason = "exact_replay" if content_hash == document.content_hash else "same_version_conflict"
        create_receipt(
            receipt_key=receipt_key,
            payload=payload,
            signature_valid=signature_valid,
            status=(
                DocumentStatus.DUPLICATE
                if reason == "exact_replay"
                else DocumentStatus.REJECTED
            ),
            reason=reason,
            document=document,
        )
        return {"accepted": True, "skipped": True, "reason": reason}

    received_at = timezone.now()
    document_values = {
        "customer_profile": identity.customer_profile,
        "identity": identity,
        "content_hash": content_hash,
        "data_structure": data_structure,
        "document_version": version,
        "observed_at": observed_at,
        "source_key": provenance["source_key"],
        "data_sources": provenance["data_sources"],
        "source_label": provenance["source_label"],
        "device_metadata": provenance["device_metadata"],
        "source_contexts": provenance["source_contexts"],
        "payload": payload,
        "status": DocumentStatus.QUEUED,
        "received_at": received_at,
        "processed_at": None,
        "failure_detail": "",
    }
    if document is None:
        document = RookHealthDocument.objects.create(
            document_identity=document_identity,
            **document_values,
        )
    else:
        for field_name, value in document_values.items():
            setattr(document, field_name, value)
        document.save()
    receipt, _ = create_receipt(
        receipt_key=receipt_key,
        payload=payload,
        signature_valid=signature_valid,
        status=DocumentStatus.QUEUED,
        reason="higher_version" if document.receipts.exists() else "accepted",
        document=document,
    )
    promote_matching_connections(
        identity=identity, connections=permitted_connections,
        observed_at=observed_at, received_at=received_at,
    )
    # Durable DB outbox: create the normalization job in the SAME transaction
    # as the accepted document. If either write fails, both roll back and ROOK
    # can safely retry the webhook; no acknowledged document is left unqueued.
    if enqueue_normalization:
        enqueue_health_job(
            job_type=HealthJobType.NORMALIZE_DOCUMENT,
            idempotency_key=f"normalize:{document.pk}:{version}:{received_at.isoformat()}",
            customer_profile=identity.customer_profile,
            document=document,
        )
    return {
        "accepted": True,
        "queued": True,
        "documentId": str(document.pk),
        "receiptId": str(receipt.pk),
        "version": version,
    }


def local_date_for_document(document: RookHealthDocument) -> date:
    timezone_name = document.identity.timezone_name
    try:
        member_timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        member_timezone = ZoneInfo("UTC")
    return document.observed_at.astimezone(member_timezone).date()


def observation_from_metric(
    *,
    document: RookHealthDocument,
    extracted_metric: ExtractedMetric,
    local_date: date,
    connection: WearableConnection | None,
) -> HealthObservation:
    observation_identity = json_digest(
        [document.document_identity, document.document_version, extracted_metric.field_path, extracted_metric.metric]
    )
    numeric_value = None
    text_value = ""
    boolean_value = None
    if isinstance(extracted_metric.value, bool):
        boolean_value = extracted_metric.value
    elif isinstance(extracted_metric.value, (int, float)):
        numeric_value = float(extracted_metric.value)
    else:
        text_value = str(extracted_metric.value)[:512]
    provenance = {
        "sourceLabel": document.source_label,
        "deviceMetadata": document.device_metadata,
        "sourceContexts": document.source_contexts,
    }
    # Only annotate; never diagnose or automatically interpret an extreme
    # observation (PRD EC-100, clinical V1). The threshold comes from the
    # explicit HR=220 example, not a universal clinical diagnosis rule.
    if (extracted_metric.metric in {"average_heart_rate", "resting_heart_rate", "maximum_heart_rate"}
            and isinstance(numeric_value, (int, float)) and numeric_value >= 220):
        provenance["clinicalReviewSuggested"] = True
        provenance["reviewReason"] = "extreme_reported_heart_rate"
    return HealthObservation(
        customer_profile=document.customer_profile,
        document=document,
        connection=connection,
        observation_identity=observation_identity,
        domain=extracted_metric.domain,
        metric=extracted_metric.metric,
        field_path=extracted_metric.field_path,
        observed_at=document.observed_at,
        local_date=local_date,
        numeric_value=numeric_value,
        text_value=text_value,
        boolean_value=boolean_value,
        unit=extracted_metric.unit,
        source_key=document.source_key,
        data_sources=document.data_sources,
        provenance=provenance,
        document_version=document.document_version,
    )


def workout_count_observation(
    *,
    document: RookHealthDocument,
    local_date: date,
    connection: WearableConnection | None,
) -> HealthObservation:
    return HealthObservation(
        customer_profile=document.customer_profile,
        document=document,
        connection=connection,
        observation_identity=json_digest([document.document_identity, document.document_version, "workout_count"]),
        domain=HealthDomain.WORKOUTS,
        metric="workout_count",
        field_path="workout_count",
        observed_at=document.observed_at,
        local_date=local_date,
        numeric_value=1.0,
        unit="sessions",
        source_key=document.source_key,
        data_sources=document.data_sources,
        provenance={
            "sourceLabel": document.source_label,
            "deviceMetadata": document.device_metadata,
        },
        document_version=document.document_version,
    )


def matching_connection(document: RookHealthDocument) -> WearableConnection | None:
    return (
        WearableConnection.objects.filter(
            customer_profile=document.customer_profile,
            data_source__in=document.data_sources,
        )
        .order_by("data_source")
        .first()
    )


def rebuild_daily_summaries(
    *,
    customer_profile,
    local_date: date,
    domains: set[str],
) -> None:
    HealthDailySummary.objects.filter(
        customer_profile=customer_profile,
        local_date=local_date,
        domain__in=domains,
    ).delete()
    grouped = (
        HealthObservation.objects.filter(
            customer_profile=customer_profile,
            local_date=local_date,
            domain__in=domains,
            numeric_value__isnull=False,
            is_current=True,
        )
        .values("domain", "metric", "source_key", "unit")
        .annotate(
            count_value=Count("id"),
            minimum_value=Min("numeric_value"),
            maximum_value=Max("numeric_value"),
            average_value=Avg("numeric_value"),
            total_value=Sum("numeric_value"),
            first_time=Min("observed_at"),
            last_time=Max("observed_at"),
        )
    )
    summaries = []
    for group in grouped.iterator():
        latest_observation = (
            HealthObservation.objects.filter(
                customer_profile=customer_profile,
                local_date=local_date,
                domain=group["domain"],
                metric=group["metric"],
                source_key=group["source_key"],
                numeric_value__isnull=False,
                is_current=True,
            )
            .order_by("-observed_at", "-created_at")
            .first()
        )
        summaries.append(
            HealthDailySummary(
                customer_profile=customer_profile,
                domain=group["domain"],
                metric=group["metric"],
                local_date=local_date,
                source_key=group["source_key"],
                count=group["count_value"],
                minimum=group["minimum_value"],
                maximum=group["maximum_value"],
                average=group["average_value"],
                total=group["total_value"],
                latest=(
                    latest_observation.numeric_value if latest_observation else None
                ),
                unit=group["unit"],
                completeness=1.0,
                first_observed_at=group["first_time"],
                last_observed_at=group["last_time"],
            )
        )
    HealthDailySummary.objects.bulk_create(summaries)


@transaction.atomic
def normalize_health_document(document_id) -> dict:
    document = (
        RookHealthDocument.objects.select_for_update()
        .select_related("identity", "customer_profile")
        .get(pk=document_id)
    )
    RookMemberIdentity.objects.select_for_update().get(pk=document.identity_id)
    if document.status == DocumentStatus.PROCESSED:
        return {"documentId": str(document.pk), "alreadyProcessed": True, "domains": []}
    from wearables.services.consent import has_active_wearable_consent
    if not has_active_wearable_consent(document.customer_profile):
        document.status = DocumentStatus.REJECTED
        document.failure_detail = "Member consent withdrawn before normalization."
        document.save(update_fields=["status", "failure_detail", "updated_at"])
        return {"skipped": True, "reason": "consent_revoked"}
    accepted, rejection = acceptable_source_connections(
        identity=document.identity,
        provenance={"data_sources": document.data_sources},
    )
    if rejection:
        document.status = DocumentStatus.REJECTED
        document.failure_detail = f"Source inactive before normalization: {rejection}"
        document.save(update_fields=["status", "failure_detail", "updated_at"])
        return {"skipped": True, "reason": rejection}
    local_date = local_date_for_document(document)
    connection = matching_connection(document)
    extracted_metrics = [
        item for item in extract_metric_values(
            document.payload, data_structure=document.data_structure,
        ) if any(source_permission_for_domain(c, item.domain) != "denied" for c in accepted)
    ]
    observations = [
        observation_from_metric(
            document=document,
            extracted_metric=extracted_metric,
            local_date=local_date,
            connection=connection,
        )
        for extracted_metric in extracted_metrics
    ]
    if (structure_represents_workout(document.data_structure)
            and any(source_permission_for_domain(c, HealthDomain.WORKOUTS) != "denied" for c in accepted)):
        observations.append(
            workout_count_observation(
                document=document,
                local_date=local_date,
                connection=connection,
            )
        )
    if not observations and connection is not None:
        # A new ROOK structure or a provider schema change must be visible to
        # operators, not silently shown as a fabricated zero.
        record_connection_event(
            connection, event_type="unmapped_or_empty_rook_document",
            previous_status=connection.status,
            detail="No supported V1 measurements were extracted from the ROOK document.",
            payload={"structure": document.data_structure[:128],
                     "documentVersion": document.document_version},
        )
    previous = document.observations.filter(is_current=True)
    for observation in observations:
        prior = (
            HealthObservation.objects.filter(
                customer_profile=document.customer_profile,
                domain=observation.domain,
                metric=observation.metric,
                is_current=True,
                observed_at__lte=observation.observed_at,
            )
            .order_by("-observed_at", "-created_at")
            .first()
        )
        if (prior and prior.source_key and observation.source_key
                and prior.source_key != observation.source_key):
            observation.provenance["sourceChange"] = {
                "from": prior.data_sources,
                "to": observation.data_sources,
                "at": observation.observed_at.isoformat(),
            }
            observation.confidence = 0.5
    affected_domains = set(previous.values_list("domain", flat=True).distinct())
    affected_domains.update(observation.domain for observation in observations)
    # Append-only: historical versions remain queryable for audit/reprocessing;
    # only the latest version participates in the dashboard and active timeline.
    previous.filter(document_version__lt=document.document_version).update(
        is_current=False, updated_at=timezone.now()
    )
    HealthObservation.objects.bulk_create(observations, ignore_conflicts=True)
    if affected_domains:
        rebuild_daily_summaries(
            customer_profile=document.customer_profile,
            local_date=local_date,
            domains=affected_domains,
        )
    document.status = DocumentStatus.PROCESSED
    document.processed_at = timezone.now()
    document.failure_detail = ""
    document.save(
        update_fields=["status", "processed_at", "failure_detail", "updated_at"]
    )
    document.receipts.filter(status=DocumentStatus.QUEUED).update(
        status=DocumentStatus.PROCESSED,
        updated_at=timezone.now(),
    )
    # Every distinct document has its own analytics work item. A date+version
    # key alone loses a second ROOK pillar delivered on the same day (A03).
    from wearables.services.analytics import invalidate_health_dashboard
    if affected_domains:
        # Store the refresh work item atomically with the processed document.
        # A post-commit scheduling error must not strand completed ingestion.
        enqueue_health_job(
            job_type=HealthJobType.REFRESH_ANALYTICS,
            idempotency_key=(
                f"analytics:{document.pk}:{document.document_version}:"
                f"{document.content_hash[:20]}"
            ),
            customer_profile=document.customer_profile,
            document=document,
            payload={"local_date": local_date.isoformat(), "domains": sorted(affected_domains)},
        )
    # Cache evictions are best-effort AFTER commit; the DB snapshot TTL bounds
    # any transient cache error, while the scheduled refresh remains durable.
    transaction.on_commit(partial(invalidate_health_dashboard, document.customer_profile), robust=True)
    return {
        "documentId": str(document.pk),
        "observationCount": len(observations),
        "v1MetricCount": sum(1 for observation in observations if is_v1_display_metric(observation.domain, observation.metric)),
        "domains": sorted(affected_domains),
        "localDate": local_date.isoformat(),
    }


@transaction.atomic
def remap_member_local_days(customer_profile) -> dict:
    """Rebuild local-day buckets after timezone travel/change, preserving UTC instants.

    The raw instant and observation version remain unchanged. Both current and
    superseded observations retain audit history; only current versions are
    rolled up into materialized summaries.
    """
    identity = RookMemberIdentity.objects.select_for_update().get(
        customer_profile=customer_profile
    )
    try:
        member_zone = ZoneInfo(identity.timezone_name)
    except ZoneInfoNotFoundError:
        member_zone = ZoneInfo("UTC")
    affected_dates: dict[date, set[str]] = {}
    updated = 0
    batch = []
    for observation in HealthObservation.objects.filter(
        customer_profile=customer_profile
    ).iterator(chunk_size=500):
        mapped = observation.observed_at.astimezone(member_zone).date()
        if mapped != observation.local_date:
            if observation.is_current:
                affected_dates.setdefault(observation.local_date, set()).add(observation.domain)
                affected_dates.setdefault(mapped, set()).add(observation.domain)
            observation.local_date = mapped
            batch.append(observation)
            updated += 1
            if len(batch) >= 500:
                HealthObservation.objects.bulk_update(batch, ["local_date"])
                batch.clear()
    if batch:
        HealthObservation.objects.bulk_update(batch, ["local_date"])
    for local_date, domains in affected_dates.items():
        rebuild_daily_summaries(
            customer_profile=customer_profile, local_date=local_date, domains=domains
        )
    from wearables.services.analytics import invalidate_health_dashboard
    transaction.on_commit(lambda: invalidate_health_dashboard(customer_profile))
    return {"remapped": updated, "affectedDates": len(affected_dates)}
