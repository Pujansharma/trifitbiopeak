from datetime import timedelta
from uuid import uuid4

from django.db import transaction
from django.db.models import Q, QuerySet
from django.utils import timezone

from wearables.models import (
    RookOutbox,
    RookHealthDocument,
    WearableConnection,
    WearableConsent,
)
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionMethod,
    ConnectionStatus,
    ConsentStatus,
    HealthJobStatus,
    HealthJobType,
    HistoricalImportStatus,
)

from wearables.services.sync_plan import create_sync_plan
from wearables.services.config import preexisting_import_enabled
from wearables.services.coordination import serialize_connection_changes
from wearables.services.job_claims import (
    maximum_rook_outbox_attempts,
    rook_outbox_exhausted_q,
    rook_outbox_retryable_q,
)
from wearables.services.sync_policy import ManualSyncCooldown, manual_sync_allowed, next_manual_sync_at
from wearables.services.wake import schedule_job_wake, mark_job_wake_pending
from wearables.services.authorization_tracking import mark_authorization_failed


def enqueue_health_job(
    *,
    job_type: str,
    idempotency_key: str,
    customer_profile=None,
    document: RookHealthDocument | None = None,
    connection: WearableConnection | None = None,
    payload: dict | None = None,
) -> RookOutbox:
    job, created = RookOutbox.objects.get_or_create(
        idempotency_key=idempotency_key,
        defaults={
            "customer_profile": customer_profile,
            "document": document,
            "connection": connection,
            "job_type": job_type,
            "status": HealthJobStatus.PENDING,
            "payload": payload or {},
            "scheduled_at": timezone.localtime(),
        },
    )
    if created:
        schedule_job_wake(job.pk)
    return job


def finished_health_jobs(jobs: QuerySet[RookOutbox]) -> QuerySet[RookOutbox]:
    """Successful or exhausted jobs, whose completed_at marks terminal finish."""
    return jobs.filter(
        Q(status=HealthJobStatus.COMPLETED)
        | Q(status=HealthJobStatus.FAILED) & rook_outbox_exhausted_q()
    )


def open_fetch_rook_data_jobs(connection: WearableConnection) -> QuerySet[RookOutbox]:
    """Find a pending, running, or retryable failed pull for this provider."""
    return RookOutbox.objects.filter(
        connection=connection, job_type=HealthJobType.FETCH_ROOK_DATA,
    ).filter(
        Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
        | Q(status=HealthJobStatus.FAILED) & rook_outbox_retryable_q()
    )


def enqueue_or_reuse_fetch_rook_data_job(
    *, connection: WearableConnection, customer_profile, manual: bool = False,
    flow: str | None = None, scheduled_key: str | None = None,
) -> tuple[RookOutbox | None, bool]:
    """Serialize enqueue per connection and freeze a resumable date window.

    First connect, manual sync and nightly all use this entrypoint.
    """
    now = timezone.localtime()
    with transaction.atomic():
        current = serialize_connection_changes(connection.pk)
        consent = WearableConsent.objects.filter(
            customer_profile=customer_profile, status=ConsentStatus.GRANTED,
            revoked_at__isnull=True,
        ).exists()
        if (not consent or current.authorization_status != AuthorizationStatus.AUTHORIZED
                or current.disconnected_at is not None
                or current.connection_method != ConnectionMethod.API
                or current.status in {ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED}
                or current.last_error_code == "provider_account_closed"):
            return None, False
        open_job = open_fetch_rook_data_jobs(current).order_by("scheduled_at", "pk").first()
        if open_job is None and scheduled_key:
            prior = RookOutbox.objects.filter(idempotency_key=scheduled_key).first()
            if prior is not None:
                return prior, False
        if open_job is None and not manual and flow not in {"initial", "nightly", "rolling"} and finished_health_jobs(
            RookOutbox.objects.filter(connection=current, job_type=HealthJobType.FETCH_ROOK_DATA)
        ).filter(completed_at__gt=now - timedelta(hours=1)).exists():
            return None, False
        is_manual_request = manual and flow in {None, "manual"}
        if is_manual_request and not manual_sync_allowed(now=now, last_accepted_at=current.last_manual_sync_queued_at):
            raise ManualSyncCooldown(next_manual_sync_at(current.last_manual_sync_queued_at),
                                     open_job.pk if open_job is not None else None)
        if is_manual_request:
            current.last_manual_sync_queued_at = now
        if is_manual_request or flow in {"nightly", "rolling"} or open_job is None:
            current.pending_sync_requested_at = max(filter(None, (current.pending_sync_requested_at, now)))
            current.last_sync_requested_at = now
            current.save(update_fields=["pending_sync_requested_at", "last_sync_requested_at",
                                        "last_manual_sync_queued_at", "updated_at"])
        if open_job is not None:
            schedule_job_wake(open_job.pk)
            return open_job, False
        effective_flow = flow or ("manual" if manual else "recovery")
        key = scheduled_key or f"sync:{current.pk}:{uuid4().hex}"
        existing = RookOutbox.objects.filter(idempotency_key=key).first()
        if existing is not None:
            return existing, False
        plan = create_sync_plan(
            requested_at=now, timezone_name=current.identity.timezone_name,
            previous_cursor=current.synced_through, flow=effective_flow,
            initial_days=current.historical_days_requested,
        )
        initial_disabled = effective_flow == "initial" and (
            not preexisting_import_enabled() or current.historical_days_requested == 0
        )
        current.import_started_at = now
        current.last_sync_requested_at = now
        current.import_status = HistoricalImportStatus.RUNNING
        current.save(update_fields=["import_started_at", "last_sync_requested_at", "import_status", "updated_at"])
        connection.import_started_at = now
        connection.last_sync_requested_at = now
        connection.import_status = current.import_status
        job = enqueue_health_job(
            job_type=HealthJobType.FETCH_ROOK_DATA, idempotency_key=key,
            customer_profile=customer_profile, connection=current,
            payload={"generation": str(current.authorization_generation), "sync": plan,
                     "initialImportDisabled": initial_disabled, "progressVersion": 1,
                     "newObservationCount": 0, "newMeasurementDomains": []},
        )
        return job, True


def enqueue_authorise_rook_connection(*, connection: WearableConnection,
                                was_reconnect: bool = False) -> RookOutbox | None:
    """Queue server-to-server grant verification, never trust browser hints."""
    with transaction.atomic():
        current = serialize_connection_changes(connection.pk)
        if (current.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}
                or current.connection_method != ConnectionMethod.API):
            return None
        job = enqueue_health_job(
            job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
            idempotency_key=f"authorization:{current.pk}:{current.authorization_generation}",
            customer_profile=current.customer_profile, connection=current,
            payload={"generation": str(current.authorization_generation),
                     "wasReconnect": was_reconnect, "requestedAt": timezone.localtime().isoformat()},
        )
        if (
            job.status == HealthJobStatus.FAILED
            and job.attempt_count >= maximum_rook_outbox_attempts(job.job_type)
        ):
            mark_authorization_failed(
                current, generation=str(current.authorization_generation),
                detail="Authorization verification stopped. Retry the connection from the app.",
            )
        return job


def cancel_connection_work(connection: WearableConnection) -> int:
    """Fence old authorization/pull work immediately when local access closes."""
    now = timezone.localtime()
    cancelled = 0
    for job_type in (HealthJobType.FETCH_ROOK_DATA, HealthJobType.AUTHORISE_ROOK_CONNECTION):
        cancelled += RookOutbox.objects.filter(
            connection=connection,
            job_type=job_type,
            status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING, HealthJobStatus.FAILED),
        ).update(
            status=HealthJobStatus.FAILED,
            attempt_count=maximum_rook_outbox_attempts(job_type),
            failure_detail="Provider authorization was revoked or replaced.",
            completed_at=now,
            locked_at=None,
            claim_token=None,
            updated_at=now,
        )
    return cancelled


def enqueue_revoke_job(connection: WearableConnection, *, explicit_retry: bool = False) -> RookOutbox:
    """Durable remote revoke; repeated user action can restart an exhausted attempt."""
    job = enqueue_health_job(
        job_type=HealthJobType.REVOKE_ROOK_CONNECTION,
        idempotency_key=f"revoke:{connection.pk}:{connection.authorization_generation}",
        customer_profile=connection.customer_profile, connection=connection,
        payload={"generation": str(connection.authorization_generation)},
    )
    if explicit_retry:
        now = timezone.localtime()
        updated = RookOutbox.objects.filter(
            pk=job.pk,
            status=HealthJobStatus.FAILED,
            attempt_count__gte=maximum_rook_outbox_attempts(HealthJobType.REVOKE_ROOK_CONNECTION),
        ).update(
            status=HealthJobStatus.PENDING,
            attempt_count=0,
            scheduled_at=now,
            started_at=None,
            completed_at=None,
            locked_at=None,
            claim_token=None,
            failure_detail="",
            payload={
                **job.payload,
                "generation": str(connection.authorization_generation),
                "operatorPreviousFailure": job.failure_detail,
            },
            updated_at=now,
        )
        if updated:
            mark_job_wake_pending(job.pk)
    return job
