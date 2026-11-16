"""Checkpointed recovery shared by initial, manual and midnight triggers.

One slice processes a bounded set of date/pillar units. Data and analytics may
be visible before complete coverage; an incomplete slice never claims full sync.
"""
from datetime import datetime
from functools import partial
from itertools import islice

from django.db import transaction
from django.utils import timezone

from wearables.models import RookOutbox, WearableConnection
from wearables.services.analytics import invalidate_health_dashboard, refresh_profile_snapshots
from wearables.services.client import RookClient, RookServiceError
from wearables.services.consent import has_active_wearable_consent
from wearables.services.coordination import serialize_profile_changes, serialize_connection_changes
from wearables.services.ingestion import ingest_rook_document, normalize_health_document
from wearables.services.job_claims import (
    SLICE_STOP_GUARD_SECONDS,
    LostHealthJobLease,
    assert_health_job_owned,
    checkpoint_health_job,
    claim_seconds_remaining,
    complete_health_job,
    defer_health_job,
    heartbeat_health_job,
)
from wearables.services.lifecycle import can_ingest_source
from wearables.services.provider_errors import RookRequestDeferred
from wearables.services.signature import rook_metadata_datetime_string
from wearables.services.provenance import extract_provenance
from wearables.services.runtime import recovery_units_per_slice, enabled_setting
from wearables.services.sync_plan import (
    advance_sync_plan, create_sync_plan, remaining_sync_units, sync_plan_complete,
)
from wearables.utils.constants import (
    ConnectionMethod, ConnectionStatus, HistoricalImportStatus, AuthorizationStatus,
)


class SyncAuthorizationChanged(RookServiceError):
    """A disconnect or replacement authorization invalidates this import."""
    terminal = True


def recovery_document(*, document: dict, rook_user_id: str, health_pillar: str,
                      summary_date: str):
    if document.get("user_id") not in (None, rook_user_id):
        raise RookServiceError("ROOK returned a document for a different member.", status_code=422)
    return {
        **document, "user_id": rook_user_id,
        "data_structure": document.get("data_structure") or f"{health_pillar}_health_summary",
        "datetime": rook_metadata_datetime_string(document) or document.get("datetime")
        or f"{summary_date}T00:00:00+00:00",
    }


def current_sync_connection(job: RookOutbox, *, for_update: bool = False):
    if for_update:
        serialize_profile_changes(job.customer_profile_id)
        connection = serialize_connection_changes(job.connection_id)
    else:
        connection = WearableConnection.objects.select_related("identity", "customer_profile").filter(pk=job.connection_id).first()
    if connection is None:
        raise SyncAuthorizationChanged("Wearable connection no longer exists.")
    if (not can_ingest_source(connection)
            or not has_active_wearable_consent(connection.customer_profile)
            or str(connection.authorization_generation) != job.payload.get("generation")):
        raise SyncAuthorizationChanged("Synchronization cancelled because authorization or consent changed.")
    assert_health_job_owned(job)
    return connection


def ensure_sync_plan(job: RookOutbox, connection: WearableConnection):
    payload = dict(job.payload)
    if "sync" not in payload:
        payload.update(progressVersion=1, newObservationCount=0, newMeasurementDomains=[])
        payload["generation"] = str(connection.authorization_generation)
        payload["sync"] = create_sync_plan(
            requested_at=timezone.localtime(), timezone_name=connection.identity.timezone_name,
            previous_cursor=connection.synced_through, flow="recovery",
            initial_days=connection.historical_days_requested,
        )
        checkpoint_health_job(job, payload)
    return payload["sync"]


def normalize_recovery_response(job: RookOutbox, connection: WearableConnection,
                                documents: list[dict], *, pillar: str, summary_date: str):
    processed = 0
    for document in documents:
        sources = set(extract_provenance(document)["data_sources"]) - {"unspecified"}
        if sources and connection.data_source not in sources:
            continue
        heartbeat_health_job(job)
        with transaction.atomic():
            current = current_sync_connection(job, for_update=True)
            result = ingest_rook_document(
                recovery_document(document=document, rook_user_id=connection.identity.rook_user_id,
                                  health_pillar=pillar, summary_date=summary_date),
                signature_valid=True, enqueue_normalization=False,
            )
            document_id = result.get("documentId")
            if not document_id:
                raise RookServiceError(f"Recovery document was not accepted: {result.get('reason', 'unknown')}")
            outcome = normalize_health_document(document_id, job=job, enqueue_analytics=False)
            if outcome.get("skipped"):
                raise RookServiceError(f"Recovery normalization incomplete: {outcome.get('reason')}")
            # Count committed new/corrected observations, not fetched duplicates.
            # Save with normalization so replay after a checkpoint crash cannot
            # count the same canonical document again.
            observation_count = outcome.get("observationCount", 0)
            if observation_count:
                current.last_data_processed_at = timezone.localtime()
                current.save(update_fields=["last_data_processed_at", "updated_at"])
                checkpoint_health_job(job, {
                    **job.payload,
                    "newObservationCount": int(job.payload.get("newObservationCount", 0)) + observation_count,
                    "newMeasurementDomains": sorted(set(job.payload.get("newMeasurementDomains", []))
                                                    | set(outcome.get("domains", []))),
                    "analyticsPending": True,
                })
            processed += int(not outcome.get("alreadyProcessed", False))
    return processed


def refresh_partial_analytics(job: RookOutbox):
    if not job.payload.get("analyticsPending"):
        return
    with transaction.atomic():
        connection = current_sync_connection(job, for_update=True)
        refresh_profile_snapshots(connection.customer_profile)
        checkpoint_health_job(job, {**job.payload, "analyticsPending": False})
        transaction.on_commit(partial(invalidate_health_dashboard, connection.customer_profile,
                                      remove_snapshots=False), robust=True)


def finish_sync(job: RookOutbox):
    """Finish coverage and its job atomically with concurrent manual admission.

    A newer accepted request becomes a fresh plan on the SAME job after the
    frozen plan finishes. Completion/enqueue cannot discard that target.
    """
    with transaction.atomic():
        connection = current_sync_connection(job, for_update=True)
        plan = job.payload["sync"]
        covered_until = datetime.fromisoformat(plan["windowEnd"])
        disabled = bool(job.payload.get("initialImportDisabled"))
        if not disabled and not sync_plan_complete(plan):
            raise ValueError("Cannot complete an unfinished synchronization window.")
        now = timezone.localtime()
        if not disabled:
            connection.synced_through = max(filter(None, (connection.synced_through, covered_until)))
            connection.last_pull_completed_at = now
            connection.last_successful_sync = now
        target = connection.pending_sync_requested_at
        followup = target is not None and target > covered_until
        connection.import_status = HistoricalImportStatus.RUNNING if followup else HistoricalImportStatus.COMPLETED
        connection.import_completed_at = None if followup else now
        connection.status = ConnectionStatus.IMPORTING if followup else (
            ConnectionStatus.ACTIVE if connection.available_to else ConnectionStatus.IDLE
        )
        connection.last_error_code = ""
        connection.last_error_detail = ""
        if not followup:
            connection.pending_sync_requested_at = None
        connection.save(update_fields=[
            "synced_through", "last_pull_completed_at", "last_successful_sync", "import_status",
            "import_completed_at", "status", "pending_sync_requested_at",
            "last_error_code", "last_error_detail", "updated_at",
        ])
        refresh_profile_snapshots(connection.customer_profile)
        assert_health_job_owned(job)
        if followup:
            next_plan = create_sync_plan(
                requested_at=target, timezone_name=connection.identity.timezone_name,
                previous_cursor=connection.synced_through, flow="followup",
                initial_days=connection.historical_days_requested,
            )
            checkpoint_health_job(job, {**job.payload, "sync": next_plan, "analyticsPending": False,
                                       "initialImportDisabled": False,
                                       "completedWindowCount": int(job.payload.get("completedWindowCount", 0)) + 1})
            result = {"deferred": True, "reason": "newer_requested_window", "retryAfterSeconds": 1,
                      "syncedThrough": connection.synced_through.isoformat() if connection.synced_through else None}
            changed = defer_health_job(job, result)
            outcome = "deferred"
        else:
            result = {"synced": not disabled, "syncedThrough": connection.synced_through.isoformat() if connection.synced_through else None,
                      "requestCount": plan["requestCount"], "importedDocumentCount": plan["documentCount"],
                      "partial": False}
            if job.payload.get("progressVersion") == 1:
                result["newObservationCount"] = int(job.payload.get("newObservationCount", 0))
            if disabled:
                result.update(skipped=True, reason="preexisting_import_disabled")
            changed = complete_health_job(job, result)
            outcome = "skipped" if disabled else "completed"
        if not changed:
            raise LostHealthJobLease("Synchronization completion lost its attempt ownership.")
        transaction.on_commit(partial(invalidate_health_dashboard, connection.customer_profile,
                                      remove_snapshots=False), robust=True)
    return {**result, "_jobFinalized": True, "_jobOutcome": outcome}


def process_fetch_rook_data(job: RookOutbox):
    if job.connection_id is None:
        raise ValueError("Health data pull job has no connection.")
    if enabled_setting("ROOK_PULLS_PAUSED", False):
        return {"deferred": True, "reason": "pulls_paused", "retryAfterSeconds": 60}
    connection = WearableConnection.objects.select_related("identity", "customer_profile").filter(pk=job.connection_id).first()
    if connection is None:
        raise SyncAuthorizationChanged("Wearable connection no longer exists.")
    if connection.connection_method != ConnectionMethod.API:
        return {"skipped": True, "reason": "sdk_history_is_on_device"}
    plan = ensure_sync_plan(job, connection)
    connection = current_sync_connection(job)
    if job.payload.get("initialImportDisabled"):
        return finish_sync(job)
    client = RookClient()
    try:
        for summary_date, pillar in islice(remaining_sync_units(plan), recovery_units_per_slice()):
            remaining = claim_seconds_remaining(job)
            if remaining is not None and remaining < SLICE_STOP_GUARD_SECONDS:
                refresh_partial_analytics(job)
                return {"deferred": True, "reason": "slice_budget", "retryAfterSeconds": 1}
            connection = current_sync_connection(job)
            heartbeat_health_job(job)
            documents = client.get_processed_summaries(
                rook_user_id=connection.identity.rook_user_id, health_pillar=pillar, summary_date=summary_date,
            )
            heartbeat_health_job(job)
            count = normalize_recovery_response(job, connection, documents, pillar=pillar, summary_date=summary_date)
            plan = advance_sync_plan(plan, summary_date=summary_date, pillar=pillar, document_count=count)
            with transaction.atomic():
                current_sync_connection(job, for_update=True)
                checkpoint_health_job(job, {**job.payload, "sync": plan,
                                           "analyticsPending": bool(count) or job.payload.get("analyticsPending", False)})
    except RookRequestDeferred:
        refresh_partial_analytics(job)
        raise
    if not sync_plan_complete(plan):
        refresh_partial_analytics(job)
        return {"deferred": True, "reason": "sync_continuation", "retryAfterSeconds": 1,
                "nextDate": plan["nextDate"], "nextPillar": plan["nextPillar"]}
    return finish_sync(job)


def save_recovery_outcome(connection: WearableConnection, *, fields: list[str]) -> None:
    """Compatibility helper for existing callers; never resurrect an old grant."""
    values = {field: getattr(connection, field) for field in fields if field != "updated_at"}
    changed = WearableConnection.objects.filter(
        pk=connection.pk, authorization_generation=connection.authorization_generation,
        import_started_at=connection.import_started_at, disconnected_at__isnull=True,
        authorization_status="authorized",
    ).exclude(status__in=(ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED)).update(
        **values, updated_at=timezone.localtime(),
    )
    if not changed:
        raise SyncAuthorizationChanged("Recovery outcome belongs to an expired authorization.")
