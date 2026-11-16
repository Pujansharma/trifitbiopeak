"""Short ORM claims, attempt fencing, and reclaim of abandoned RUNNING jobs."""
from datetime import timedelta
from random import uniform
from uuid import UUID, uuid4

from django.db import transaction
from django.db.models import Case, DateTimeField, F, Q, Value, When
from django.utils import timezone

from wearables.models import RookOutbox, WearableConnection
from wearables.services.authorization_tracking import mark_authorization_failed
from wearables.services.coordination import serialize_connection_changes
from wearables.services.progress_policy import failure_recovery_action
from wearables.services.provider_errors import RookConfigurationError
from wearables.utils.constants import (
    MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
    MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
    AuthorizationStatus,
    HealthJobStatus,
    HealthJobType,
    HistoricalImportStatus,
)

STALE_JOB_MINUTES = 15
# Soft stop for multi-slice fetch within one claim (no deadline_at column).
MAX_FETCH_CLAIM_SECONDS = 780
SLICE_STOP_GUARD_SECONDS = 35


class LostHealthJobLease(RuntimeError):
    """The caller no longer owns the current job attempt."""


def maximum_rook_outbox_attempts(job_type: str) -> int:
    if job_type == HealthJobType.FETCH_ROOK_DATA:
        return MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS
    return MAX_ROOK_AUTH_OUTBOX_ATTEMPTS


def rook_outbox_retryable_q() -> Q:
    return (
        Q(
            job_type=HealthJobType.FETCH_ROOK_DATA,
            attempt_count__lt=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
        )
        | Q(
            job_type__in=(
                HealthJobType.AUTHORISE_ROOK_CONNECTION,
                HealthJobType.REVOKE_ROOK_CONNECTION,
            ),
            attempt_count__lt=MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
        )
    )


def rook_outbox_exhausted_q() -> Q:
    return (
        Q(
            job_type=HealthJobType.FETCH_ROOK_DATA,
            attempt_count__gte=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
        )
        | Q(
            job_type__in=(
                HealthJobType.AUTHORISE_ROOK_CONNECTION,
                HealthJobType.REVOKE_ROOK_CONNECTION,
            ),
            attempt_count__gte=MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
        )
    )


def owned_health_job(job: RookOutbox):
    return RookOutbox.objects.filter(
        pk=job.pk,
        status=HealthJobStatus.RUNNING,
        claim_token=job.claim_token,
        started_at=job.started_at,
        attempt_count=job.attempt_count,
    )


def assert_health_job_owned(job: RookOutbox) -> None:
    query = owned_health_job(job)
    # Conditional UPDATE fences commit against a concurrent timeout/reclaim.
    valid = (
        query.update(locked_at=F("locked_at"))
        if transaction.get_connection().in_atomic_block
        else query.exists()
    )
    if not valid:
        raise LostHealthJobLease("Health job ownership expired.")


def heartbeat_health_job(job: RookOutbox) -> None:
    now = timezone.localtime()
    updated = owned_health_job(job).update(locked_at=now, updated_at=now)
    if not updated:
        raise LostHealthJobLease("Health job ownership expired.")


def claim_seconds_remaining(job: RookOutbox) -> float | None:
    if job.started_at is None or job.job_type != HealthJobType.FETCH_ROOK_DATA:
        return None
    elapsed = (timezone.localtime() - job.started_at).total_seconds()
    return MAX_FETCH_CLAIM_SECONDS - elapsed


def claim_health_job(job_id) -> RookOutbox | None:
    now = timezone.localtime()
    token = uuid4()
    with transaction.atomic():
        candidate = RookOutbox.objects.filter(pk=job_id).first()
        if candidate is None:
            return None
        max_attempts = maximum_rook_outbox_attempts(candidate.job_type)
        if candidate.job_type == HealthJobType.FETCH_ROOK_DATA:
            if candidate.connection_id is None:
                return None
            current = serialize_connection_changes(candidate.connection_id)
            if (
                current.authorization_status != AuthorizationStatus.AUTHORIZED
                or current.disconnected_at is not None
            ):
                RookOutbox.objects.filter(
                    pk=job_id,
                    status__in=(HealthJobStatus.PENDING, HealthJobStatus.FAILED),
                ).update(
                    status=HealthJobStatus.FAILED,
                    attempt_count=max_attempts,
                    failure_detail="Recovery authorization is no longer active.",
                    completed_at=now,
                    locked_at=None,
                    claim_token=None,
                    updated_at=now,
                )
                return None
            if RookOutbox.objects.filter(
                connection_id=candidate.connection_id,
                job_type=HealthJobType.FETCH_ROOK_DATA,
                status=HealthJobStatus.RUNNING,
            ).exclude(pk=job_id).exists():
                return None
        updated = RookOutbox.objects.filter(
            pk=job_id,
            status__in=(HealthJobStatus.PENDING, HealthJobStatus.FAILED),
            scheduled_at__lte=now,
            attempt_count__lt=max_attempts,
        ).update(
            status=HealthJobStatus.RUNNING,
            started_at=now,
            locked_at=now,
            claim_token=token,
            attempt_count=F("attempt_count") + 1,
            failure_detail="",
            updated_at=now,
        )
        if not updated:
            return None
        # Fetch ONLY our claim, never a successor's attempt after a reclaim.
        return RookOutbox.objects.select_related(
            "customer_profile",
            "document",
            "connection__identity",
        ).filter(pk=job_id, claim_token=token, started_at=now).first()


def checkpoint_health_job(job: RookOutbox, payload: dict) -> None:
    now = timezone.localtime()
    if not owned_health_job(job).update(
        payload=payload,
        locked_at=now,
        updated_at=now,
    ):
        raise LostHealthJobLease("Cannot checkpoint a superseded health job.")
    job.payload = payload


def complete_health_job(job: RookOutbox, result: dict) -> bool:
    now = timezone.localtime()
    return bool(owned_health_job(job).update(
        status=HealthJobStatus.COMPLETED,
        payload={**job.payload, "result": result},
        completed_at=now,
        locked_at=None,
        updated_at=now,
    ))


def defer_health_job(job: RookOutbox, result: dict) -> bool:
    """A bounded continuation is not a failure and must not spend retry budget."""
    now = timezone.localtime()
    return bool(owned_health_job(job).update(
        status=HealthJobStatus.PENDING,
        attempt_count=F("attempt_count") - 1,
        payload={**job.payload, "result": result},
        scheduled_at=now + timedelta(seconds=max(1, int(result.get("retryAfterSeconds", 30)))),
        completed_at=None,
        locked_at=None,
        claim_token=None,
        wake_version=F("wake_version") + 1,
        wake_next_attempt_at=None,
        updated_at=now,
    ))


def fail_health_job(job: RookOutbox, error: BaseException, *, terminal: bool = False) -> bool:
    now = timezone.localtime()
    max_attempts = maximum_rook_outbox_attempts(job.job_type)
    count = max_attempts if terminal else job.attempt_count
    # Use the same connection -> job lock order as admission/claims. An old
    # failure must never overwrite the status of a newly admitted operation.
    with transaction.atomic():
        current = None
        if job.job_type in {
            HealthJobType.FETCH_ROOK_DATA,
            HealthJobType.AUTHORISE_ROOK_CONNECTION,
        } and job.connection_id:
            current = WearableConnection.objects.filter(pk=job.connection_id).first()
            if current is not None:
                current = serialize_connection_changes(job.connection_id)
        changed = bool(owned_health_job(job).update(
            status=HealthJobStatus.FAILED,
            failure_detail=str(error)[:512],
            scheduled_at=now + timedelta(
                seconds=min(900, 30 * 2 ** max(count - 1, 0)) + uniform(0, 10)
            ),
            attempt_count=count,
            wake_version=F("wake_version") + 1,
            wake_next_attempt_at=None,
            completed_at=now if count >= max_attempts else None,
            locked_at=None,
            updated_at=now,
            payload={
                **job.payload,
                "failure": {
                    "statusCode": getattr(error, "status_code", None),
                    "recoveryAction": failure_recovery_action(
                        job_type=job.job_type,
                        status_code=getattr(error, "status_code", 0),
                        configuration_error=isinstance(error, RookConfigurationError),
                    ),
                },
            },
        ))
        if (
            changed
            and current is not None
            and job.job_type == HealthJobType.FETCH_ROOK_DATA
            and current.authorization_status == AuthorizationStatus.AUTHORIZED
            and current.disconnected_at is None
            and str(current.authorization_generation) == job.payload.get("generation")
        ):
            current.import_status = (
                HistoricalImportStatus.PARTIAL
                if job.payload.get("sync", {}).get("requestCount")
                else HistoricalImportStatus.FAILED
            )
            current.last_error_code = "sync_attempt_failed"
            current.last_error_detail = str(error)[:512]
            current.save(update_fields=[
                "import_status",
                "last_error_code",
                "last_error_detail",
                "updated_at",
            ])
        if (
            changed
            and current is not None
            and job.job_type == HealthJobType.AUTHORISE_ROOK_CONNECTION
            and count >= max_attempts
        ):
            mark_authorization_failed(
                current,
                generation=job.payload.get("generation", ""),
                detail="Authorization could not be confirmed. Retry the connection from the app.",
            )
    return changed


def reset_stale_health_jobs() -> list[UUID]:
    """Fail abandoned RUNNING rows; return reclaimed PKs for optional SQS wake."""
    now = timezone.localtime()
    expired = Q(locked_at__lt=now - timedelta(minutes=STALE_JOB_MINUTES))
    expired |= Q(locked_at__isnull=True, started_at__lt=now - timedelta(minutes=STALE_JOB_MINUTES))
    stale_ids = list(
        RookOutbox.objects.filter(status=HealthJobStatus.RUNNING)
        .filter(expired)
        .order_by("pk")
        .values_list("pk", flat=True)[:100]
    )
    if not stale_ids:
        return []
    RookOutbox.objects.filter(pk__in=stale_ids).update(
        status=HealthJobStatus.FAILED,
        failure_detail="Worker execution abandoned; reclaimed as stale.",
        scheduled_at=now,
        completed_at=Case(
            When(
                job_type=HealthJobType.FETCH_ROOK_DATA,
                attempt_count__gte=MAX_ROOK_DATA_FETCH_OUTBOX_ATTEMPTS,
                then=Value(now),
            ),
            When(
                job_type__in=(
                    HealthJobType.AUTHORISE_ROOK_CONNECTION,
                    HealthJobType.REVOKE_ROOK_CONNECTION,
                ),
                attempt_count__gte=MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
                then=Value(now),
            ),
            default=Value(None),
            output_field=DateTimeField(),
        ),
        locked_at=None,
        wake_version=F("wake_version") + 1,
        wake_next_attempt_at=None,
        updated_at=now,
    )
    return stale_ids
