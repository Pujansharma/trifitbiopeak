import hashlib
from collections import defaultdict
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
    WearableConsent,
    WearableConnection,
)
from wearables.services.connections import (
    get_or_create_connection,
    record_connection_event,
)
from wearables.services.job_queue import enqueue_health_job
from wearables.services.metrics import (
    ExtractedMetric,
    extract_metric_values,
    structure_represents_workout,
)
from wearables.services.provenance import extract_provenance
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    ConsentStatus,
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


def find_first_value(node: Any, field_names: list[str]) -> Any:
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
    root_order = ("datetime", "datetime_string", "date_time", "start_datetime_string")
    for field_name in root_order:
        value = payload.get(field_name)
        if value is not None:
            return value
    return find_first_value(payload, DOCUMENT_TIME_FIELDS)


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
    return RookWebhookReceipt.objects.get_or_create(
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


def wearable_source_values() -> set[str]:
    return {choice.value for choice in WearableSource}


def promote_matching_connections(
    *,
    identity: RookMemberIdentity,
    data_sources: list[str],
    observed_at: datetime,
    received_at: datetime,
) -> None:
    for data_source in data_sources:
        if data_source not in wearable_source_values():
            continue
        connection = get_or_create_connection(
            customer_profile=identity.customer_profile,
            identity=identity,
            data_source=data_source,
            historical_days_requested=None,
        )
        previous_status = connection.status
        connection.last_webhook_received_at = received_at
        connection.available_from = min(
            filter(None, [connection.available_from, observed_at]),
            default=observed_at,
        )
        connection.available_to = max(
            filter(None, [connection.available_to, observed_at]),
            default=observed_at,
        )
        if connection.status not in {
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.AUTHORIZATION_EXPIRED,
        }:
            connection.status = ConnectionStatus.ACTIVE
            connection.authorization_status = AuthorizationStatus.AUTHORIZED
            if connection.permission_status in {
                PermissionStatus.UNKNOWN,
                PermissionStatus.NOT_DETERMINED,
            }:
                connection.permission_status = PermissionStatus.GRANTED
            # Receiving a live document proves sync, not that the entire
            # historical import completed. ROOK import/recovery completion
            # is reported separately; keep the progressive-import state.
            connection.last_successful_sync = received_at
            connection.connected_at = connection.connected_at or received_at
        connection.save()
        if previous_status != connection.status:
            record_connection_event(
                connection,
                event_type="webhook_data_received",
                previous_status=previous_status,
                detail="Connection promoted after verified ROOK data delivery.",
            )


@transaction.atomic
def ingest_rook_document(payload: dict, *, signature_valid: bool) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("ROOK webhook document must be an object.")
    content_hash = json_digest(payload)
    receipt_key = json_digest([content_hash, payload.get("user_id")])
    existing_receipt = RookWebhookReceipt.objects.filter(
        receipt_key=receipt_key
    ).first()
    if existing_receipt is not None:
        return {
            "accepted": True,
            "duplicate": True,
            "reason": existing_receipt.reason or "exact_replay",
        }

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

    # A recorded withdrawal blocks further ingestion for this customer profile.
    # Legacy records with no consent row are not silently rejected here; the
    # connect endpoint enforces explicit consent for all new connections.
    active_consent = WearableConsent.objects.filter(
        customer_profile=identity.customer_profile,
        status=ConsentStatus.GRANTED,
        revoked_at__isnull=True,
    ).exists()
    prior_revocation = WearableConsent.objects.filter(
        customer_profile=identity.customer_profile,
        status=ConsentStatus.REVOKED,
    ).exists()
    if prior_revocation and not active_consent:
        create_receipt(
            receipt_key=receipt_key,
            payload=payload,
            signature_valid=signature_valid,
            status=DocumentStatus.REJECTED,
            reason="consent_revoked",
        )
        return {"accepted": True, "skipped": True, "reason": "consent_revoked"}

    observed_at = parse_document_datetime(payload)
    data_structure = document_structure(payload)
    version = document_version(payload)
    provenance = extract_provenance(payload)
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
    if document is not None and version == document.document_version:
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
        identity=identity,
        data_sources=provenance["data_sources"],
        observed_at=observed_at,
        received_at=received_at,
    )
    from wearables.services.analytics import invalidate_health_dashboard
    transaction.on_commit(partial(invalidate_health_dashboard, identity.customer_profile))
    transaction.on_commit(
        partial(
            enqueue_health_job,
            job_type=HealthJobType.NORMALIZE_DOCUMENT,
            idempotency_key=f"normalize:{document.pk}:{version}",
            customer_profile=identity.customer_profile,
            document=document,
        )
    )
    return {
        "accepted": True,
        "queued": True,
        "documentId": str(document.pk),
        "receiptId": str(receipt.pk),
        "version": version,
    }


def local_date_for_instant(document: RookHealthDocument, observed_at: datetime) -> date:
    timezone_name = document.identity.timezone_name
    try:
        member_timezone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        member_timezone = ZoneInfo("UTC")
    return observed_at.astimezone(member_timezone).date()


def local_date_for_document(document: RookHealthDocument) -> date:
    return local_date_for_instant(document, document.observed_at)


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
    observed_at = extracted_metric.observed_at or document.observed_at
    local_date = (
        local_date_for_instant(document, observed_at)
        if extracted_metric.observed_at is not None
        else local_date
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
    return HealthObservation(
        customer_profile=document.customer_profile,
        document=document,
        connection=connection,
        observation_identity=observation_identity,
        domain=extracted_metric.domain,
        metric=extracted_metric.metric,
        field_path=extracted_metric.field_path,
        observed_at=observed_at,
        local_date=local_date,
        numeric_value=numeric_value,
        text_value=text_value,
        boolean_value=boolean_value,
        unit=extracted_metric.unit,
        source_key=document.source_key,
        data_sources=document.data_sources,
        provenance={
            "sourceLabel": document.source_label,
            "deviceMetadata": document.device_metadata,
            "sourceContexts": document.source_contexts,
        },
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
    local_date = local_date_for_document(document)
    connection = matching_connection(document)
    extracted_metrics = list(
        extract_metric_values(
            document.payload,
            data_structure=document.data_structure,
        )
    )
    observations = [
        observation_from_metric(
            document=document,
            extracted_metric=extracted_metric,
            local_date=local_date,
            connection=connection,
        )
        for extracted_metric in extracted_metrics
    ]
    if structure_represents_workout(document.data_structure):
        observations.append(
            workout_count_observation(
                document=document,
                local_date=local_date,
                connection=connection,
            )
        )
    previous = document.observations.filter(is_current=True)
    # Query source continuity once per canonical metric, not once per reading.
    # Event payloads may include thousands of heart-rate readings; a per-event
    # PostgreSQL query was a major remote-DB latency/SSL risk.
    earliest_by_metric: dict[tuple[str, str], HealthObservation] = {}
    for observation in observations:
        metric_key = (observation.domain, observation.metric)
        earliest = earliest_by_metric.get(metric_key)
        if earliest is None or observation.observed_at < earliest.observed_at:
            earliest_by_metric[metric_key] = observation
    for earliest in earliest_by_metric.values():
        prior = (
            HealthObservation.objects.filter(
                customer_profile=document.customer_profile,
                domain=earliest.domain,
                metric=earliest.metric,
                is_current=True,
                observed_at__lte=earliest.observed_at,
            )
            .order_by("-observed_at", "-created_at")
            .first()
        )
        if (prior and prior.source_key and earliest.source_key
                and prior.source_key != earliest.source_key):
            earliest.provenance["sourceChange"] = {
                "from": prior.data_sources,
                "to": earliest.data_sources,
                "at": earliest.observed_at.isoformat(),
            }
            earliest.confidence = 0.5
    domains_by_day: dict[date, set[str]] = defaultdict(set)
    for previous_day, previous_domain in previous.values_list("local_date", "domain"):
        domains_by_day[previous_day].add(previous_domain)
    for observation in observations:
        domains_by_day[observation.local_date].add(observation.domain)
    affected_domains = set().union(*domains_by_day.values()) if domains_by_day else set()
    # Append-only: historical versions remain queryable for audit/reprocessing;
    # only the latest version participates in the dashboard and active timeline.
    previous.filter(document_version__lt=document.document_version).update(
        is_current=False, updated_at=timezone.now()
    )
    # Keep inserts small: high-resolution ROOK events can carry thousands of readings.
    HealthObservation.objects.bulk_create(observations, batch_size=200, ignore_conflicts=True)
    for affected_date, daily_domains in sorted(domains_by_day.items()):
        rebuild_daily_summaries(
            customer_profile=document.customer_profile,
            local_date=affected_date,
            domains=daily_domains,
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
    transaction.on_commit(
        partial(
            enqueue_health_job,
            job_type=HealthJobType.REFRESH_ANALYTICS,
            idempotency_key=(
                f"analytics:{document.pk}:{document.document_version}"
            ),
            customer_profile=document.customer_profile,
            payload={
                "local_dates": [day.isoformat() for day in sorted(domains_by_day)],
                "domains": sorted(affected_domains),
            },
        )
    )
    return {
        "documentId": str(document.pk),
        "observationCount": len(observations),
        "domains": sorted(affected_domains),
        "localDate": local_date.isoformat(),
        "affectedLocalDates": [day.isoformat() for day in sorted(domains_by_day)],
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
