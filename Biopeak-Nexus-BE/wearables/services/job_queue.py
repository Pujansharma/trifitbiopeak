from datetime import timedelta

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from wearables.models import (
    HealthProcessingJob,
    RookHealthDocument,
    WearableConnection,
)
from wearables.utils.constants import (
    HEALTH_MAXIMUM_JOB_ATTEMPTS, HealthJobStatus, HealthJobType, HistoricalImportStatus,
)


def enqueue_health_job(
    *,
    job_type: str,
    idempotency_key: str,
    customer_profile=None,
    document: RookHealthDocument | None = None,
    connection: WearableConnection | None = None,
    payload: dict | None = None,
) -> HealthProcessingJob:
    job, _ = HealthProcessingJob.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "customer_profile": customer_profile,
            "document": document,
            "connection": connection,
            "job_type": job_type,
            "status": HealthJobStatus.PENDING,
            "payload": payload or {},
            "scheduled_at": timezone.now(),
        },
    )
    return job



def open_recovery_jobs(connection: WearableConnection) -> QuerySet[HealthProcessingJob]:
    """Find a pending, running, or retryable failed pull for this provider."""
    return HealthProcessingJob.objects.filter(
        connection=connection, job_type=HealthJobType.RECOVERY_PULL,
    ).filter(
        Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
        | Q(status=HealthJobStatus.FAILED, attempt_count__lt=HEALTH_MAXIMUM_JOB_ATTEMPTS)
    )


def enqueue_or_reuse_recovery_job(
    *, connection: WearableConnection, customer_profile, manual: bool = False,
) -> tuple[HealthProcessingJob | None, bool]:
    """Enqueue a single open pull per connection across manual and scheduled requests.

    Compare-and-swap on import_started_at serializes concurrent first writers
    without select_for_update or a new migration. The winning transaction
    persists the generation marker and the new job atomically.
    """
    with transaction.atomic():
        open_job = open_recovery_jobs(connection).order_by("scheduled_at", "pk").first()
        if open_job is not None:
            if manual and open_job.status == HealthJobStatus.FAILED:
                now = timezone.now()
                HealthProcessingJob.objects.filter(
                    pk=open_job.pk, status=HealthJobStatus.FAILED,
                    attempt_count__lt=HEALTH_MAXIMUM_JOB_ATTEMPTS,
                ).update(scheduled_at=now, updated_at=now)
                open_job.scheduled_at = now
            return open_job, False

        now = timezone.now()
        # Preserve the scheduler's previous hourly pacing. A recovery that
        # completed recently must not be recreated by the next 15-minute sweep;
        # a deliberate manual retry may still start a new attempt.
        if not manual and HealthProcessingJob.objects.filter(
            connection=connection, job_type=HealthJobType.RECOVERY_PULL,
            created_at__gte=now - timedelta(hours=1),
        ).exists():
            return None, False
        updates = {"import_started_at": now, "updated_at": now}
        if manual:
            updates["import_status"] = HistoricalImportStatus.RUNNING
        claimed = WearableConnection.objects.filter(
            pk=connection.pk,
            status=connection.status,
            authorization_status=connection.authorization_status,
            import_started_at=connection.import_started_at,
        ).update(**updates)
        if not claimed:
            # Another process has changed the connection (or just queued a
            # recovery). A subsequent SELECT sees committed claims.
            return open_recovery_jobs(connection).order_by("scheduled_at", "pk").first(), False

        connection.import_started_at = now
        if manual:
            connection.import_status = HistoricalImportStatus.RUNNING
        job = enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=f"recovery:{connection.pk}:{now.strftime('%Y%m%d%H%M%S%f')}",
            customer_profile=customer_profile,
            connection=connection,
        )
        return job, True
