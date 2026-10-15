from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections
from django.db.models import F, Q
from django.utils import timezone

from wearables.models import HealthProcessingJob, WearableConnection
from wearables.services.analytics import refresh_profile_snapshots
from wearables.services.client import (
    RookClient,
    ROOK_PROCESSED_EVENT_TYPES,
    RookConfigurationError,
    RookServiceError,
)
from wearables.services.connections import refresh_authorizing_connections
from wearables.services.ingestion import (
    document_datetime_value, ingest_rook_document, normalize_health_document,
    parse_document_datetime, remap_member_local_days,
)
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionMethod,
    ConnectionStatus,
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
        "datetime": document.get("datetime")
        or f"{summary_date}T00:00:00+00:00",
    }


def recovery_event_document(
    *,
    document: dict,
    rook_user_id: str,
    health_pillar: str,
    event_type: str,
) -> dict:
    """Never invent an event time: missing event timestamps require investigation."""
    value = document_datetime_value(document)
    if value is None:
        raise ValueError("ROOK processed event is missing its measurement datetime.")
    moment = parse_document_datetime({"datetime": value})
    return {
        **document,
        "user_id": rook_user_id,
        "data_structure": document.get("data_structure") or f"{health_pillar}_health_events_{event_type}",
        "datetime": moment.isoformat(),
    }


def process_recovery_pull(job: HealthProcessingJob) -> dict:
    if job.connection_id is None:
        raise ValueError("Recovery pull job has no connection.")
    connection = WearableConnection.objects.select_related("identity").get(
        pk=job.connection_id
    )
    if connection.status == ConnectionStatus.DISCONNECTED:
        return {"skipped": True, "reason": "connection_disconnected"}
    client = RookClient()
    imported_count = 0
    event_count = 0
    error_count = 0
    request_count = 0
    failed_request_count = 0
    # API-based ROOK Pre-Existing Data is limited to seven days. Native SDK
    # backfill (up to ~29 days) happens on-device, not through this endpoint.
    from wearables.services.analytics import member_today

    today = member_today(connection.customer_profile)
    requested_days = min(connection.historical_days_requested, 7)
    if requested_days == 0:
        connection.status = ConnectionStatus.IDLE
        connection.import_status = HistoricalImportStatus.COMPLETED
        connection.import_completed_at = timezone.now()
        connection.save(update_fields=["status", "import_status", "import_completed_at", "updated_at"])
        from wearables.services.analytics import invalidate_health_dashboard
        invalidate_health_dashboard(connection.customer_profile)
        return {"skipped": True, "reason": "preexisting_import_disabled"}
    for day_offset in range(requested_days):
        summary_date = (today - timedelta(days=day_offset)).isoformat()
        for health_pillar in ("physical", "sleep", "body"):
            request_count += 1
            try:
                documents = client.get_processed_summaries(
                    rook_user_id=connection.identity.rook_user_id,
                    health_pillar=health_pillar,
                    summary_date=summary_date,
                )
            except RookServiceError:
                error_count += 1
                failed_request_count += 1
                continue
            for document in documents:
                result = ingest_rook_document(
                    recovery_document(
                        document=document,
                        rook_user_id=connection.identity.rook_user_id,
                        health_pillar=health_pillar,
                        summary_date=summary_date,
                    ),
                    signature_valid=True,
                )
                imported_count += int(result.get("queued", False))
        if (
            getattr(settings, "ROOK_RECOVERY_INCLUDE_EVENTS", False)
            and day_offset < max(0, min(getattr(settings, "ROOK_RECOVERY_EVENT_DAYS", 1), 7))
        ):
            for health_pillar, event_types in ROOK_PROCESSED_EVENT_TYPES.items():
                for event_type in event_types:
                    request_count += 1
                    try:
                        events = client.get_processed_events(
                            rook_user_id=connection.identity.rook_user_id,
                            health_pillar=health_pillar,
                            event_type=event_type,
                            event_date=summary_date,
                        )
                    except RookServiceError:
                        error_count += 1
                        failed_request_count += 1
                        continue
                    # A response with unbounded events can exceed the worker's
                    # lease. Do not silently truncate it; record a partial import.
                    if len(events) > getattr(settings, "ROOK_RECOVERY_MAX_EVENTS_PER_REQUEST", 500):
                        error_count += 1
                        continue
                    for event in events:
                        try:
                            event_document = recovery_event_document(
                                document=event,
                                rook_user_id=connection.identity.rook_user_id,
                                health_pillar=health_pillar,
                                event_type=event_type,
                            )
                        except ValueError:
                            error_count += 1
                            continue
                        result = ingest_rook_document(event_document, signature_valid=True)
                        event_count += int(result.get("queued", False))
    if failed_request_count == request_count and request_count:
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
    connection.last_successful_sync = timezone.now()
    if error_count:
        connection.status = ConnectionStatus.PARTIAL
        connection.import_status = HistoricalImportStatus.PARTIAL
        connection.last_error_code = "recovery_partial"
        connection.last_error_detail = (
            f"{error_count} of {request_count} recovery requests were unavailable."
        )
    else:
        connection.status = (
            ConnectionStatus.ACTIVE if (imported_count or event_count) else ConnectionStatus.IDLE
        )
        connection.import_status = HistoricalImportStatus.COMPLETED
        connection.last_error_code = ""
        connection.last_error_detail = ""
        connection.import_completed_at = timezone.now()
    connection.save(
        update_fields=[
            "authorization_status",
            "last_successful_sync",
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
        "importedEventDocumentCount": event_count,
        "partial": error_count > 0,
        "errorCount": error_count,
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


def reset_stale_health_jobs(*, customer_profile_id=None) -> int:
    stale_before = timezone.now() - timedelta(minutes=STALE_JOB_MINUTES)
    stale_jobs = HealthProcessingJob.objects.filter(
        status=HealthJobStatus.RUNNING,
        locked_at__lt=stale_before,
    )
    if customer_profile_id is not None:
        stale_jobs = stale_jobs.filter(customer_profile_id=customer_profile_id)
    return stale_jobs.update(
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


def process_pending_health_jobs(
    *, limit: int = 50, customer_profile_id=None
) -> list[dict]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    reset_stale_health_jobs(customer_profile_id=customer_profile_id)
    eligible_jobs = HealthProcessingJob.objects.filter(
        status__in=[HealthJobStatus.PENDING, HealthJobStatus.FAILED],
        scheduled_at__lte=timezone.now(),
        attempt_count__lt=MAXIMUM_JOB_ATTEMPTS,
    )
    if customer_profile_id is not None:
        eligible_jobs = eligible_jobs.filter(customer_profile_id=customer_profile_id)
    job_ids = list(
        eligible_jobs.order_by("scheduled_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )
    results = []
    handled_errors = (
        RookServiceError,
        RookConfigurationError,
        ValueError,
        WearableConnection.DoesNotExist,
    )
    for job_id in job_ids:
        # Recycle unhealthy/stale DB sockets before each independent job.
        # Critical for long-running health batches on remote PostgreSQL.
        close_old_connections()
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
        ],
        connection_method=ConnectionMethod.API,
    ).filter(
        Q(last_successful_sync__isnull=True)
        | Q(last_successful_sync__lt=delayed_before)
    )

