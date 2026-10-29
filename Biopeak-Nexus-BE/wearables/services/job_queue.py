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



def open_freshness_jobs(customer_profile) -> QuerySet[HealthProcessingJob]:
    """Freshness jobs that have not finished their permitted attempts."""
    return HealthProcessingJob.objects.filter(
        customer_profile=customer_profile, job_type=HealthJobType.FRESHNESS_CHECK,
    ).filter(
        Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
        | Q(status=HealthJobStatus.FAILED, attempt_count__lt=HEALTH_MAXIMUM_JOB_ATTEMPTS)
    )


def enqueue_or_reuse_freshness_job(
    *, customer_profile, now=None,
) -> tuple[HealthProcessingJob | None, bool]:
    """One in-flight freshness check per profile, one reusable row per profile.

    A permanent idempotency key is safe across concurrent sweep commands: the
    database unique index arbitrates the first creation; a conditional update
    arbitrates hourly re-enqueue after completion. Legacy hourly keys remain
    readable and are allowed to drain before a new check is scheduled.
    """
    now = now or timezone.now()
    existing_open = open_freshness_jobs(customer_profile).order_by("scheduled_at", "pk").first()
    if existing_open is not None:
        return existing_open, False

    interval_start = now - timedelta(hours=1)
    # A pre-upgrade hourly job may have just completed. Do not immediately
    # replace it with a new fixed-key job before the next hourly interval.
    if HealthProcessingJob.objects.filter(
        customer_profile=customer_profile, job_type=HealthJobType.FRESHNESS_CHECK,
        scheduled_at__gt=interval_start,
    ).exists():
        return None, False

    job, created = HealthProcessingJob.objects.get_or_create(
        idempotency_key=f"freshness:{customer_profile.pk}",
        defaults={
            "customer_profile": customer_profile,
            "job_type": HealthJobType.FRESHNESS_CHECK,
            "status": HealthJobStatus.PENDING,
            "scheduled_at": now,
        },
    )
    if created:
        return job, True

    # A completed (or exhausted) job may be reused; its attempt count must
    # reset, otherwise the existing worker will never claim a new occurrence.
    updated = HealthProcessingJob.objects.filter(
        pk=job.pk,
        status__in=(HealthJobStatus.COMPLETED, HealthJobStatus.FAILED),
        scheduled_at__lte=interval_start,
    ).filter(
        Q(status=HealthJobStatus.COMPLETED)
        | Q(attempt_count__gte=HEALTH_MAXIMUM_JOB_ATTEMPTS)
    ).update(
        status=HealthJobStatus.PENDING, attempt_count=0,
        scheduled_at=now, started_at=None, completed_at=None,
        locked_at=None, failure_detail="", payload={}, updated_at=now,
    )
    return job, bool(updated)


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
