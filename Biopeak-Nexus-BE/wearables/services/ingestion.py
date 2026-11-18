import hashlib
import json
from datetime import UTC, date, datetime, time
from functools import partial
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from wearables.models import (
    HealthDailySummary,
    RookMemberIdentity,
    RookWebhookReceipt,
    WearableConnection,
)
from wearables.services.analytics import invalidate_health_dashboard, refresh_profile_snapshots
from wearables.services.client import RookServiceError
from wearables.services.connections import record_connection_event
from wearables.services.consent import has_active_wearable_consent
from wearables.services.coordination import serialize_profile_changes
from wearables.services.daily_contributions import (
    add_value,
    drop_contribution,
    local_date_for,
    mark_clinical_review,
    new_entry,
    prior_summary_row,
    recompute_or_delete,
    upsert_contribution,
    upsert_contributions,
)
from wearables.services.job_claims import assert_health_job_owned
from wearables.services.lifecycle import can_ingest_source, source_permission_for_domain
from wearables.services.metrics import (
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

# Outcomes where a delivery is already represented by a processed version. They are
# final answers for ROOK (accepted, no data change), not retryable failures.
SETTLED_DUPLICATE_REASONS = frozenset({"lower_document_version", "exact_replay", "same_version_conflict"})


class RookIngestionStateChanged(RookServiceError):
    """Retryable conflict: source authorization changed during ingestion.

    Raising from the atomic ingestion function rolls back the receipt and any
    connection writes. The webhook boundary must return a non-2xx response so
    ROOK knows the delivery was *not* accepted.
    """


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
    identity_key: str = "",
    version: int = 1,
    content_hash: str = "",
    observed_at: datetime | None = None,
) -> tuple[RookWebhookReceipt, bool]:
    # A queued delivery keeps the raw body until it is processed; every other
    # outcome keeps only the compact, non-clinical summary.
    stored_payload = payload if status == DocumentStatus.QUEUED else receipt_payload(payload)
    receipt, created = RookWebhookReceipt.objects.get_or_create(
        receipt_key=receipt_key,
        defaults={
            "rook_user_id": str(payload.get("user_id") or "")[:50],
            "document_identity": identity_key,
            "document_version": version,
            "content_hash": content_hash,
            "observed_at": observed_at,
            "signature_valid": signature_valid,
            "status": status,
            "reason": reason[:128],
            "payload": stored_payload,
            "received_at": timezone.localtime(),
        },
    )
    # Rejected source/consent deliveries may be resubmitted after an explicit
    # reauthorization. A past rejection must not become a permanent gap.
    if not created and receipt.status == DocumentStatus.REJECTED and status == DocumentStatus.QUEUED:
        receipt.document_identity = identity_key
        receipt.document_version = version
        receipt.content_hash = content_hash
        receipt.observed_at = observed_at
        receipt.signature_valid = signature_valid
        receipt.status = status
        receipt.reason = reason[:128]
        receipt.payload = stored_payload
        receipt.received_at = timezone.localtime()
        receipt.save(update_fields=[
            "document_identity", "document_version", "content_hash", "observed_at",
            "signature_valid", "status", "reason", "payload", "received_at", "updated_at",
        ])
    return receipt, created


def wearable_source_values() -> set[str]:
    return {choice.value for choice in WearableSource}


def acceptable_source_connections(*, identity, provenance: dict) -> tuple[list, str]:
    """Reject deliveries from unlinked, disconnected or unpermitted sources.

    ROOK may return a provider-resolved document with multiple source labels.
    To guarantee a revoked source cannot contribute, every identified source
    must remain authorized. An unattributed ROOK document is only accepted
    when one eligible connection exists (never guess between two providers).
    Concurrent authorization changes are detected by a conditional update
    on the connection before the webhook transaction can commit.
    """
    available = list(WearableConnection.objects.filter(
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


def resolved_data_sources(provenance: dict, permitted_connections: list) -> list[str]:
    """Unattributed deliveries are attributed only when the single eligible connection is unambiguous."""
    if provenance["data_sources"] == ["unspecified"]:
        return [permitted_connections[0].data_source]
    return list(provenance["data_sources"])


def promote_matching_connections(
    *, identity: RookMemberIdentity,
    connections: list[WearableConnection],
    observed_at: datetime, received_at: datetime,
) -> bool:
    accepted_count = 0
    for connection in connections:
        if not can_ingest_source(connection):
            continue
        previous_status = connection.status
        connection.last_webhook_received_at = received_at
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
        updates = {
            "last_webhook_received_at": connection.last_webhook_received_at,
            "connected_at": connection.connected_at,
            "available_from": connection.available_from,
            "available_to": connection.available_to,
            "status": connection.status,
            "last_error_code": connection.last_error_code,
            "last_error_detail": connection.last_error_detail,
            "updated_at": timezone.localtime(),
        }
        changed = WearableConnection.objects.filter(
            pk=connection.pk, status=previous_status,
            authorization_status=connection.authorization_status,
            permission_status=connection.permission_status,
        ).update(**updates)
        if not changed:
            # A concurrent disconnect/revocation takes precedence over data.
            continue
        accepted_count += 1
        if previous_status != connection.status:
            record_connection_event(
                connection, event_type="webhook_data_received",
                previous_status=previous_status,
                detail="Authorized source delivered a verified ROOK document.",
            )
    return accepted_count == len(connections)


def current_processed_receipt(identity_key: str):
    """The highest processed version for one canonical ROOK document."""
    if not identity_key:
        return None
    return (
        RookWebhookReceipt.objects.filter(
            document_identity=identity_key,
            status=DocumentStatus.PROCESSED,
        )
        .order_by("-document_version", "-received_at")
        .first()
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
    # A rejected delivery is still subject to all current source and consent
    # checks below; never blindly trust an old rejection.
    if existing_receipt is not None and existing_receipt.status != DocumentStatus.REJECTED:
        return {
            "accepted": True,
            "duplicate": True,
            "reason": existing_receipt.reason or "exact_replay",
            "documentId": str(existing_receipt.pk),
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
        RookMemberIdentity.objects
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

    # Serialize local consent changes with short ingestion/normalization writes.
    serialize_profile_changes(identity.customer_profile_id)
    # DPDP: a delayed/replayed webhook must not create new observations after
    # the member has withdrawn all wearable-ingestion consent.
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
    identity_key = document_identity_digest(
        customer_profile_id=identity.customer_profile_id,
        data_structure=data_structure,
        observed_at=observed_at,
        payload=payload,
    )
    received_at = timezone.localtime()

    # Fast-path correction check. The authoritative check repeats under the
    # member's profile lock inside normalize_health_document.
    current = current_processed_receipt(identity_key)
    reason = ""
    if current is not None:
        if version < current.document_version:
            reason = "lower_document_version"
        elif version == current.document_version:
            reason = "exact_replay" if content_hash == current.content_hash else "same_version_conflict"
    if reason:
        receipt, _ = create_receipt(
            receipt_key=receipt_key, payload=payload,
            signature_valid=signature_valid,
            status=(DocumentStatus.DUPLICATE if reason == "exact_replay" else DocumentStatus.REJECTED),
            reason=reason, identity_key=identity_key, version=version,
            content_hash=content_hash, observed_at=observed_at,
        )
        return {"accepted": True, "skipped": True, "reason": reason, "documentId": str(receipt.pk)}

    receipt, _ = create_receipt(
        receipt_key=receipt_key,
        payload=payload,
        signature_valid=signature_valid,
        status=DocumentStatus.QUEUED,
        reason="higher_version" if current is not None else "accepted",
        identity_key=identity_key,
        version=version,
        content_hash=content_hash,
        observed_at=observed_at,
    )
    if not promote_matching_connections(
        identity=identity, connections=permitted_connections,
        observed_at=observed_at, received_at=received_at,
    ):
        # A disconnect may have raced the initial consent/source check.
        # Raising rolls back the receipt and connection updates.
        # Never acknowledge this retryable race as accepted to ROOK: a 2xx
        # response would make the provider permanently discard the delivery.
        raise RookIngestionStateChanged(
            "ROOK source authorization changed during ingestion; retry delivery.",
            status_code=503,
        )
    # Webhook path finishes normalize + analytics in this same accept transaction.
    # Failure rolls the receipt back so ROOK can retry; the raw body is cleared
    # after successful processing (see normalize_health_document).
    processed = None
    if enqueue_normalization:
        processed = normalize_health_document(
            receipt.pk,
            enqueue_analytics=True,
        )
        if processed.get("skipped") and processed.get("reason") not in (
            SETTLED_DUPLICATE_REASONS | {"already_processing_or_not_queued"}
        ):
            raise RookIngestionStateChanged(
                f"ROOK document could not be normalized: {processed.get('reason')}",
                status_code=503,
            )
    return {
        "accepted": True,
        "queued": not enqueue_normalization,
        "processed": bool(enqueue_normalization),
        "documentId": str(receipt.pk),
        "receiptId": str(receipt.pk),
        "version": version,
        "normalize": processed,
    }


def matching_connection(customer_profile, data_sources: list[str]) -> WearableConnection | None:
    return (
        WearableConnection.objects.filter(
            customer_profile=customer_profile,
            data_source__in=data_sources,
        )
        .order_by("data_source")
        .first()
    )


def _reject_queued_receipt(receipt: RookWebhookReceipt, *, status: str, reason: str) -> dict:
    RookWebhookReceipt.objects.filter(pk=receipt.pk).update(
        status=status,
        reason=reason[:128],
        payload={},
        updated_at=timezone.localtime(),
    )
    return {"skipped": True, "reason": reason, "documentId": str(receipt.pk)}


@transaction.atomic
def normalize_health_document(document_id, *, job=None, enqueue_analytics: bool = True) -> dict:
    """Turn one queued ROOK delivery into per-day summary contributions.

    ``document_id`` is the ``RookWebhookReceipt`` primary key (returned as
    ``documentId`` by the ingestion functions).
    """
    receipt = RookWebhookReceipt.objects.filter(pk=document_id).first()
    if receipt is None:
        raise ValueError("Health document no longer exists.")
    identity = (
        RookMemberIdentity.objects
        .select_related("customer_profile")
        .filter(rook_user_id=receipt.rook_user_id)
        .first()
    )
    if identity is None:
        raise ValueError("Wearable identity no longer exists.")
    profile = identity.customer_profile
    serialize_profile_changes(profile.pk)
    if job is not None:
        assert_health_job_owned(job)
    if receipt.status == DocumentStatus.PROCESSED:
        return {"documentId": str(receipt.pk), "alreadyProcessed": True, "domains": []}
    # Reuse RECEIVED as a short-lived, transaction-scoped processing marker.
    # A crash rolls it back to QUEUED.
    claimed = RookWebhookReceipt.objects.filter(
        pk=receipt.pk, status=DocumentStatus.QUEUED,
    ).update(status=DocumentStatus.RECEIVED, updated_at=timezone.localtime())
    if not claimed:
        return {"skipped": True, "reason": "already_processing_or_not_queued"}
    receipt.status = DocumentStatus.RECEIVED
    payload = receipt.payload or {}

    if not has_active_wearable_consent(profile):
        return _reject_queued_receipt(
            receipt, status=DocumentStatus.REJECTED, reason="consent_revoked",
        )

    # Authoritative correction ordering, serialized by the profile lock above.
    current = current_processed_receipt(receipt.document_identity)
    if current is not None:
        reason = ""
        if receipt.document_version < current.document_version:
            reason = "lower_document_version"
        elif receipt.document_version == current.document_version:
            reason = ("exact_replay" if receipt.content_hash == current.content_hash
                      else "same_version_conflict")
        if reason:
            return _reject_queued_receipt(
                receipt,
                status=DocumentStatus.DUPLICATE if reason == "exact_replay" else DocumentStatus.REJECTED,
                reason=reason,
            )

    provenance = extract_provenance(payload)
    accepted, rejection = acceptable_source_connections(
        identity=identity, provenance=provenance,
    )
    if rejection:
        return _reject_queued_receipt(
            receipt, status=DocumentStatus.REJECTED,
            reason=f"source_inactive_before_normalization:{rejection}",
        )
    data_sources = resolved_data_sources(provenance, accepted)
    source_key = provenance["source_key"]
    structure = document_structure(payload)
    observed_at = receipt.observed_at or parse_document_datetime(payload)
    local_date = local_date_for(observed_at, identity.timezone_name)
    connection = matching_connection(profile, data_sources)
    identity_key = receipt.document_identity
    version = receipt.document_version

    values: list[tuple[str, str, str, Any]] = [
        (item.domain, item.metric, item.unit, item.value)
        for item in extract_metric_values(payload, data_structure=structure)
        if any(source_permission_for_domain(c, item.domain) != "denied" for c in accepted)
    ]
    if (structure_represents_workout(structure)
            and any(source_permission_for_domain(c, HealthDomain.WORKOUTS) != "denied" for c in accepted)):
        values.append((HealthDomain.WORKOUTS, "workout_count", "sessions", 1.0))
    if not values and connection is not None:
        # A new ROOK structure or a provider schema change must be visible to
        # operators, not silently shown as a fabricated zero.
        record_connection_event(
            connection, event_type="unmapped_or_empty_rook_document",
            previous_status=connection.status,
            detail="No supported V1 measurements were extracted from the ROOK document.",
            payload={"structure": structure[:128], "documentVersion": version},
        )

    # One entry per (domain, metric) for this document. Values extracted from the
    # same document share its observed_at, so the entry is the document's exact share.
    per_metric: dict[tuple[str, str], dict] = {}
    for domain, metric, unit, value in values:
        entry = per_metric.get((domain, metric))
        if entry is None:
            entry = new_entry(
                version=version, unit=unit, observed_at=observed_at, data_sources=data_sources,
            )
            per_metric[(domain, metric)] = entry
        add_value(entry, value)
        mark_clinical_review(entry, metric, value)

    # Device-methodology change: discount confidence when the source differs from the
    # latest stored row for the same metric (PRD §8.3). Values are still shown.
    for (domain, metric), entry in per_metric.items():
        prior = prior_summary_row(profile, domain=domain, metric=metric, observed_at=observed_at)
        if prior and prior.source_key and source_key and prior.source_key != source_key:
            entry["sc"] = {"from": prior.data_sources, "to": data_sources, "at": observed_at.astimezone(UTC).isoformat()}
            entry["cf"] = 0.5

    affected_domains: set[str] = set()
    # Corrections replace this document's share wherever it was stored (any day),
    # so the previous version can never linger in a summary row.
    for row in list(HealthDailySummary.objects.filter(
        customer_profile=profile, contributions__has_key=identity_key,
    )):
        affected_domains.add(row.domain)
        drop_contribution(row, identity_key)
    for (domain, metric), entry in per_metric.items():
        upsert_contribution(
            customer_profile=profile, domain=domain, metric=metric,
            local_date=local_date, source_key=source_key,
            identity_key=identity_key, entry=entry,
        )
        affected_domains.add(domain)

    receipt.status = DocumentStatus.PROCESSED
    receipt.payload = receipt_payload(payload)
    receipt.save(update_fields=["status", "payload", "updated_at"])
    # Queued deliveries for this document at or below the processed version are
    # covered by it; release their raw bodies.
    if identity_key:
        RookWebhookReceipt.objects.filter(
            document_identity=identity_key,
            status=DocumentStatus.QUEUED,
            document_version__lte=version,
        ).exclude(pk=receipt.pk).update(
            status=DocumentStatus.PROCESSED,
            payload={},
            updated_at=timezone.localtime(),
        )
    if affected_domains and enqueue_analytics:
        refresh_profile_snapshots(profile, domains=sorted(affected_domains))
        WearableConnection.objects.filter(
            customer_profile_id=profile.pk,
            data_source__in=data_sources,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            disconnected_at__isnull=True,
        ).update(
            last_data_processed_at=timezone.localtime(),
            last_successful_sync=timezone.localtime(),
            updated_at=timezone.localtime(),
        )
    if job is not None:
        assert_health_job_owned(job)
    # Cache evictions are best-effort AFTER commit; the DB snapshot TTL bounds
    # any transient cache error after analytical rows are durable.
    transaction.on_commit(partial(invalidate_health_dashboard, profile), robust=True)
    return {
        "documentId": str(receipt.pk),
        "observationCount": len(values),
        "v1MetricCount": sum(1 for domain, metric, _unit, _value in values if is_v1_display_metric(domain, metric)),
        "domains": sorted(affected_domains),
        "localDate": local_date.isoformat(),
    }


def rebuild_daily_summaries(
    *,
    customer_profile,
    local_date: date,
    domains: set[str],
) -> None:
    """Recompute aggregates for one local day from the stored per-document entries."""
    for row in list(HealthDailySummary.objects.filter(
        customer_profile=customer_profile,
        local_date=local_date,
        domain__in=domains,
    )):
        recompute_or_delete(row)


def remap_member_local_days(customer_profile) -> dict:
    """Move stored per-document entries to their new local day after a timezone change.

    The UTC instant stored with each entry is authoritative, so no measurement is
    invented; only the day an entry is filed under changes. Work is batched and
    each batch re-checks the timezone so an obsolete remap cannot finish.
    """
    identity = RookMemberIdentity.objects.filter(
        customer_profile=customer_profile,
    ).first()
    if identity is None:
        raise ValueError("Wearable identity no longer exists.")
    timezone_name = identity.timezone_name
    member_zone = ZoneInfo(timezone_name) if _valid_zone(timezone_name) else ZoneInfo("UTC")
    row_ids = list(
        HealthDailySummary.objects.filter(customer_profile=customer_profile)
        .order_by("pk").values_list("pk", flat=True)
    )
    moved = 0
    affected_dates: set[date] = set()
    for start in range(0, len(row_ids), 500):
        batch = row_ids[start:start + 500]
        if not RookMemberIdentity.objects.filter(
            pk=identity.pk, timezone_name=timezone_name,
        ).exists():
            raise ValueError("Timezone changed while remapping; retry against latest timezone.")
        with transaction.atomic():
            for row_pk in batch:
                # Re-read each row when reached: an earlier row in this batch may
                # have moved entries into it, and a stale copy must never be saved.
                row = HealthDailySummary.objects.select_for_update().filter(pk=row_pk).first()
                if row is None:
                    continue
                by_day: dict[date, dict] = {}
                for identity_key, entry in row.contributions.items():
                    mapped = datetime.fromisoformat(entry["at"]).astimezone(member_zone).date()
                    if mapped != row.local_date:
                        by_day.setdefault(mapped, {})[identity_key] = entry
                if not by_day:
                    continue
                moving = {key for entries in by_day.values() for key in entries}
                row.contributions = {
                    key: value for key, value in row.contributions.items() if key not in moving
                }
                for mapped, entries in by_day.items():
                    upsert_contributions(
                        customer_profile=customer_profile, domain=row.domain, metric=row.metric,
                        local_date=mapped, source_key=row.source_key, entries=entries,
                    )
                    affected_dates.add(mapped)
                    moved += len(entries)
                affected_dates.add(row.local_date)
                recompute_or_delete(row)
    invalidate_health_dashboard(customer_profile)
    return {"remapped": moved, "affectedDates": len(affected_dates)}


def _valid_zone(timezone_name: str) -> bool:
    try:
        ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True
