from datetime import timedelta

from django.conf import settings
from django.db import DatabaseError
from django.db.models import F, Q
from django.utils import timezone

from wearables.models import HealthProcessingJob, RookHealthDocument, WearableConnection, WearableConnectionEvent
from wearables.services.analytics import refresh_profile_snapshots
from wearables.services.client import (
    RookClient,
    RookConfigurationError,
    RookServiceError,
)
from wearables.services.connections import refresh_authorizing_connections
from wearables.services.lifecycle import can_ingest_source
from wearables.services.job_queue import enqueue_health_job
from wearables.services.ingestion import (
    ingest_rook_document, normalize_health_document, remap_member_local_days,
)
from wearables.services.signature import rook_metadata_datetime_string
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionMethod,
    ConnectionStatus,
    DocumentStatus,
    HealthJobStatus,
    HealthJobType,
    HistoricalImportStatus,
)

MAXIMUM_JOB_ATTEMPTS = 3
STALE_JOB_MINUTES = 15


def process_normalize_document(job: HealthProcessingJob) -> dict:
    if job.document_id is None:
        raise ValueError("Normalize job has no document.")
    return normalize_health_document(job.document_id)


def process_refresh_analytics(job: HealthProcessingJob) -> dict:
    if job.customer_profile_id is None:
        raise ValueError("Analytics job has no customer profile.")
    cards = refresh_profile_snapshots(job.customer_profile, domains=job.payload.get("domains"))
    return {"cardCount": len(cards)}


def process_refresh_connection(job: HealthProcessingJob) -> dict:
    if job.customer_profile_id is None:
        raise ValueError("Connection refresh job has no customer profile.")
    refresh_authorizing_connections(job.customer_profile)
    return {"refreshed": True}


def process_revoke_connection(job: HealthProcessingJob) -> dict:
    if job.connection_id is None:
        raise ValueError("Revoke job has no connection.")
    connection = WearableConnection.objects.select_related("identity").get(
        pk=job.connection_id
    )
    # A delayed revoke from a former disconnect must not revoke a new
    # authorization created before the worker processes the old job.
    if connection.status != ConnectionStatus.DISCONNECTED:
        return {"skipped": True, "reason": "connection_reauthorized"}
    RookClient().revoke_source(
        rook_user_id=connection.identity.rook_user_id,
        data_source=connection.data_source,
    )
    connection.last_error_code = ""
    connection.last_error_detail = ""
    connection.save(
        update_fields=["last_error_code", "last_error_detail", "updated_at"]
    )
    return {"revoked": True}


def recovery_document(
    *,
    document: dict,
    rook_user_id: str,
    health_pillar: str,
    summary_date: str,
) -> dict:
    return {
        **document,
        "user_id": rook_user_id,
        "data_structure": document.get("data_structure")
        or f"{health_pillar}_health_summary",
        "datetime": (rook_metadata_datetime_string(document)
                     or document.get("datetime")
                     or f"{summary_date}T00:00:00+00:00"),
    }


def process_recovery_pull(job: HealthProcessingJob) -> dict:
    if job.connection_id is None:
        raise ValueError("Recovery pull job has no connection.")
    connection = WearableConnection.objects.select_related("identity").get(
        pk=job.connection_id
    )
    if not can_ingest_source(connection):
        return {"skipped": True, "reason": "source_not_authorized"}
    if connection.connection_method != ConnectionMethod.API:
        return {"skipped": True, "reason": "sdk_history_is_on_device"}
    from wearables.services.consent import has_active_wearable_consent
    if not has_active_wearable_consent(connection.customer_profile):
        return {"skipped": True, "reason": "consent_revoked"}
    client = RookClient()
    imported_count = 0
    already_processed_count = 0
    error_count = 0
    failed_documents = 0
    unmapped_documents = 0
    # API-based ROOK Pre-Existing Data is limited to seven days. Native SDK
    # backfill (up to ~29 days) happens on-device, not through this endpoint.
    from wearables.services.analytics import member_today

    today = member_today(connection.customer_profile)
    from wearables.services.config import preexisting_import_enabled
    requested_days = min(connection.historical_days_requested, 7) if preexisting_import_enabled() else 0
    # For short-gap reconnects, fetch only affected local days. For gaps
    # longer than ROOK's historical window, leave old missing days visible.
    if connection.status == ConnectionStatus.HISTORICAL_REIMPORT:
        revoked_event = WearableConnectionEvent.objects.filter(
            connection=connection, event_type="connection_revoked",
        ).order_by("-created_at").first()
        if revoked_event:
            elapsed = max(1, (timezone.now() - revoked_event.created_at).days + 1)
            requested_days = min(requested_days, elapsed)
    if requested_days == 0:
        connection.status = (ConnectionStatus.ACTIVE if connection.last_successful_sync else ConnectionStatus.IDLE)
        connection.import_status = HistoricalImportStatus.COMPLETED
        connection.import_completed_at = timezone.now()
        connection.save(update_fields=["status", "import_status", "import_completed_at", "updated_at"])
        from wearables.services.analytics import invalidate_health_dashboard
        invalidate_health_dashboard(connection.customer_profile)
        return {"skipped": True, "reason": "preexisting_import_disabled"}
    for day_offset in range(requested_days):
        summary_date = (today - timedelta(days=day_offset)).isoformat()
        for health_pillar in ("physical", "sleep", "body"):
            try:
                documents = client.get_processed_summaries(
                    rook_user_id=connection.identity.rook_user_id,
                    health_pillar=health_pillar,
                    summary_date=summary_date,
                )
            except RookServiceError:
                error_count += 1
                continue
            for document in documents:
                # We are already in a retryable worker. Normalize *now* before
                # updating the import status, otherwise 201/queued can be
                # mistaken for a completed historical import (PRD section 5.2).
                try:
                    result = ingest_rook_document(
                        recovery_document(
                            document=document,
                            rook_user_id=connection.identity.rook_user_id,
                            health_pillar=health_pillar,
                            summary_date=summary_date,
                        ), signature_valid=True, enqueue_normalization=False,
                    )
                    if result.get("queued"):
                        outcome = normalize_health_document(result["documentId"])
                        if outcome.get("skipped"):
                            failed_documents += 1
                        elif outcome.get("alreadyProcessed"):
                            already_processed_count += 1
                        elif not outcome.get("v1MetricCount", 0):
                            # EC-025/EC-074: an otherwise well-formed ROOK
                            # document without V1 measurements is not a local
                            # normalization failure. Retain it for drift audit.
                            unmapped_documents += 1
                        else:
                            imported_count += 1
                    elif result.get("reason") in ("exact_replay", "same_version_conflict"):
                        # Already-processed duplicates must not be re-imported.
                        already_processed_count += 1
                    else:
                        failed_documents += 1
                except (ValueError, RookServiceError) as error:
                    # A partial import must remain visible; never report a
                    # clean COMPLETED when normalization failed.
                    failed_documents += 1
                    continue
    request_count = requested_days * 3
    if error_count == request_count:
        connection.status = ConnectionStatus.PROVIDER_ERROR
        connection.import_status = HistoricalImportStatus.FAILED
        connection.last_error_code = "recovery_unavailable"
        connection.last_error_detail = (
            f"All {request_count} recovery requests were unavailable. Stored history is safe."
        )
        connection.save(
            update_fields=[
                "status",
                "import_status",
                "last_error_code",
                "last_error_detail",
                "updated_at",
            ]
        )
        raise RookServiceError(
            "ROOK recovery data was unavailable. Stored health history is safe."
        )
    connection.authorization_status = AuthorizationStatus.AUTHORIZED
    # A 200 response with no summaries does not demonstrate successful live
    # synchronization; preserve the actual last received measurement time.
    if failed_documents and not imported_count and not already_processed_count and not error_count:
        connection.status = ConnectionStatus.PROVIDER_ERROR
        connection.import_status = HistoricalImportStatus.FAILED
        connection.last_error_code = "recovery_normalization_failed"
        connection.last_error_detail = (
            f"All {failed_documents} ROOK documents failed V1 normalization; "
            "previously stored history remains safe."
        )
    elif error_count or failed_documents:
        connection.status = ConnectionStatus.PARTIAL
        connection.import_status = HistoricalImportStatus.PARTIAL
        connection.last_error_code = "recovery_partial"
        connection.last_error_detail = (
            f"{error_count} of {request_count} recovery requests unavailable; "
            f"{failed_documents} documents failed validation or normalization."
        )
    else:
        connection.status = (
            ConnectionStatus.ACTIVE if (imported_count or connection.last_successful_sync)
            else ConnectionStatus.IDLE
        )
        connection.import_status = HistoricalImportStatus.COMPLETED
        connection.last_error_code = ""
        connection.last_error_detail = ""
        connection.import_completed_at = timezone.now()
    connection.save(
        update_fields=[
            "authorization_status",
            "status",
            "import_status",
            "last_error_code",
            "last_error_detail",
            "import_completed_at",
            "updated_at",
        ]
    )
    from wearables.services.analytics import invalidate_health_dashboard
    invalidate_health_dashboard(connection.customer_profile)
    return {
        "importedDocumentCount": imported_count,
        "partial": bool(error_count or failed_documents),
        "errorCount": error_count,
        "failedDocumentCount": failed_documents,
        "unmappedDocumentCount": unmapped_documents,
        "alreadyProcessedCount": already_processed_count,
    }


def process_remap_timezone(job: HealthProcessingJob) -> dict:
    if job.customer_profile_id is None:
        raise ValueError("Timezone remap job has no customer profile.")
    result = remap_member_local_days(job.customer_profile)
    refresh_profile_snapshots(job.customer_profile)
    return result


def process_freshness_check(job: HealthProcessingJob) -> dict:
    if job.customer_profile_id is None:
        raise ValueError("Freshness job has no customer profile.")
    refresh_profile_snapshots(job.customer_profile)
    return {"refreshed": True}


JOB_HANDLERS = {
    HealthJobType.NORMALIZE_DOCUMENT: process_normalize_document,
    HealthJobType.REFRESH_ANALYTICS: process_refresh_analytics,
    HealthJobType.REFRESH_CONNECTION: process_refresh_connection,
    HealthJobType.REVOKE_CONNECTION: process_revoke_connection,
    HealthJobType.RECOVERY_PULL: process_recovery_pull,
    HealthJobType.FRESHNESS_CHECK: process_freshness_check,
    HealthJobType.REMAP_TIMEZONE: process_remap_timezone,
}


def reset_stale_health_jobs() -> int:
    stale_before = timezone.now() - timedelta(minutes=STALE_JOB_MINUTES)
    return HealthProcessingJob.objects.filter(
        status=HealthJobStatus.RUNNING,
        locked_at__lt=stale_before,
    ).update(
        status=HealthJobStatus.FAILED,
        failure_detail="Worker lease expired.",
        scheduled_at=timezone.now(),
        locked_at=None,
        updated_at=timezone.now(),
    )


def claim_health_job(job_id) -> HealthProcessingJob | None:
    now = timezone.now()
    updated = HealthProcessingJob.objects.filter(
        pk=job_id,
        status__in=[HealthJobStatus.PENDING, HealthJobStatus.FAILED],
        scheduled_at__lte=now,
        attempt_count__lt=MAXIMUM_JOB_ATTEMPTS,
    ).update(
        status=HealthJobStatus.RUNNING,
        started_at=now,
        locked_at=now,
        attempt_count=F("attempt_count") + 1,
        failure_detail="",
        updated_at=now,
    )
    if not updated:
        return None
    return HealthProcessingJob.objects.select_related(
        "customer_profile",
        "document",
        "connection__identity",
    ).get(pk=job_id)


def complete_health_job(job: HealthProcessingJob, result: dict) -> None:
    HealthProcessingJob.objects.filter(pk=job.pk).update(
        status=HealthJobStatus.COMPLETED,
        payload={**job.payload, "result": result},
        completed_at=timezone.now(),
        locked_at=None,
        updated_at=timezone.now(),
    )


def fail_health_job(job: HealthProcessingJob, error: Exception) -> None:
    retry_delay = timedelta(minutes=5 * max(job.attempt_count, 1))
    HealthProcessingJob.objects.filter(pk=job.pk).update(
        status=HealthJobStatus.FAILED,
        failure_detail=str(error)[:512],
        scheduled_at=timezone.now() + retry_delay,
        locked_at=None,
        updated_at=timezone.now(),
    )


def process_health_job(job: HealthProcessingJob) -> dict:
    handler = JOB_HANDLERS.get(job.job_type)
    if handler is None:
        raise ValueError(f"Unsupported health job type: {job.job_type}")
    return handler(job)


def process_pending_health_jobs(*, limit: int = 50) -> list[dict]:
    reset_stale_health_jobs()
    job_ids = list(
        HealthProcessingJob.objects.filter(
            status__in=[HealthJobStatus.PENDING, HealthJobStatus.FAILED],
            scheduled_at__lte=timezone.now(),
            attempt_count__lt=MAXIMUM_JOB_ATTEMPTS,
        )
        .order_by("scheduled_at")
        .values_list("pk", flat=True)[:limit]
    )
    results = []
    handled_errors = (
        RookServiceError,
        RookConfigurationError,
        ValueError,
        TypeError,
        DatabaseError,
        RookHealthDocument.DoesNotExist,
        WearableConnection.DoesNotExist,
    )
    for job_id in job_ids:
        job = claim_health_job(job_id)
        if job is None:
            continue
        try:
            result = process_health_job(job)
        except handled_errors as error:
            fail_health_job(job, error)
            results.append(
                {"jobId": str(job.pk), "status": "failed", "detail": str(error)}
            )
            continue
        complete_health_job(job, result)
        results.append({"jobId": str(job.pk), "status": "completed", **result})
    return results


def profiles_requiring_freshness_check():
    return (
        WearableConnection.objects.filter(
            status__in=[
                ConnectionStatus.ACTIVE,
                ConnectionStatus.IDLE,
                ConnectionStatus.PARTIAL,
            ]
        )
        .values_list("customer_profile_id", flat=True)
        .distinct()
    )


def connections_requiring_recovery_pull():
    delayed_before = timezone.now() - timedelta(
        hours=getattr(settings, "ROOK_SYNC_DELAY_HOURS", 48)
    )
    return WearableConnection.objects.filter(
        status__in=[
            ConnectionStatus.ACTIVE,
            ConnectionStatus.IDLE,
            ConnectionStatus.PARTIAL,
            ConnectionStatus.PROVIDER_ERROR,
            ConnectionStatus.IMPORTING,
            ConnectionStatus.HISTORICAL_REIMPORT,
        ],
        connection_method=ConnectionMethod.API,
        authorization_status=AuthorizationStatus.AUTHORIZED,
    ).filter(
        Q(last_successful_sync__isnull=True)
        | Q(last_successful_sync__lt=delayed_before)
        | Q(import_status__in=[HistoricalImportStatus.RUNNING, HistoricalImportStatus.PARTIAL],
            import_started_at__lt=timezone.now() - timedelta(hours=4))
    )



def enqueue_orphaned_normalization_jobs(*, grace_minutes: int = 10, limit: int = 100) -> dict:
    """Recover queued documents with no runnable normalization work item.

    A terminated worker or a pre-upgrade on_commit failure can leave accepted
    webhook data without its processing job. Never retry a document whose
    normalization already exhausted its bounded attempt budget; alert ops.
    """
    cutoff = timezone.now() - timedelta(minutes=max(1, grace_minutes))
    unprocessed = RookHealthDocument.objects.filter(
        status=DocumentStatus.QUEUED,
        received_at__lt=cutoff,
    ).order_by("received_at")[:max(1, limit)]
    queued_count = 0
    exhausted_count = 0
    for document in unprocessed.iterator():
        normalize_jobs = HealthProcessingJob.objects.filter(
            document=document, job_type=HealthJobType.NORMALIZE_DOCUMENT,
        )
        if normalize_jobs.filter(
            Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
            | Q(status=HealthJobStatus.FAILED,
                attempt_count__lt=MAXIMUM_JOB_ATTEMPTS)
        ).exists():
            continue
        if normalize_jobs.filter(
            status=HealthJobStatus.FAILED,
            attempt_count__gte=MAXIMUM_JOB_ATTEMPTS,
        ).exists():
            exhausted_count += 1
            continue
        enqueue_health_job(
            job_type=HealthJobType.NORMALIZE_DOCUMENT,
            idempotency_key=(f"orphan-normalize:{document.pk}:"
                             f"{document.document_version}:{document.content_hash[:16]}"),
            customer_profile=document.customer_profile,
            document=document,
        )
        queued_count += 1
    return {"queued": queued_count, "requiresOperatorReview": exhausted_count}
