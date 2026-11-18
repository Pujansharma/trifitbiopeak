"""Dispatch ROOK outbox jobs; claims and fetch recovery stay separate."""
from uuid import UUID

from django.conf import settings
from django.db import DatabaseError
from django.db.models import Case, IntegerField, Value, When
from django.utils import timezone

from integrations.utils.sqs_dispatch import delete_queue_message
from wearables.models import RookOutbox, RookWebhookReceipt, WearableConnection
from wearables.services.authorization_jobs import (
    process_authorise_rook_connection,
    process_revoke_rook_connection,
)
from wearables.services.client import RookConfigurationError, RookServiceError
from wearables.services.job_claims import (
    LostHealthJobLease,
    claim_health_job,
    complete_health_job,
    defer_health_job,
    fail_health_job,
    maximum_rook_outbox_attempts,
    reset_stale_health_jobs,
    rook_outbox_retryable_q,
)
from wearables.services.provider_errors import RookRequestDeferred
from wearables.services.rate_policy import seconds_until
from wearables.services.recovery import process_fetch_rook_data
from wearables.services.runtime import enabled_setting
from wearables.services.wake import (
    QUEUE_KIND_AUTH,
    QUEUE_KIND_DATA_FETCH,
    queue_kind,
    schedule_job_wake,
)
from wearables.utils.constants import HealthJobStatus, HealthJobType

MAXIMUM_FETCH_ROOK_DATA_PER_SWEEP = 1

JOB_HANDLERS = {
    HealthJobType.AUTHORISE_ROOK_CONNECTION: process_authorise_rook_connection,
    HealthJobType.REVOKE_ROOK_CONNECTION: process_revoke_rook_connection,
    HealthJobType.FETCH_ROOK_DATA: process_fetch_rook_data,
}


def schedule_retry_wake(job: RookOutbox, *, force: bool = False) -> None:
    """Publish SQS wake after defer, or after fail while attempts remain."""
    if force:
        schedule_job_wake(job.pk)
        return
    job.refresh_from_db(fields=["attempt_count", "job_type", "completed_at"])
    if job.completed_at is not None:
        return
    if job.attempt_count >= maximum_rook_outbox_attempts(job.job_type):
        return
    schedule_job_wake(job.pk)


def process_health_job(job: RookOutbox) -> dict:
    handler = JOB_HANDLERS.get(job.job_type)
    if handler is None:
        raise ValueError(f"Unsupported health job type: {job.job_type}")
    return handler(job)


def run_claimed_health_job(job: RookOutbox) -> dict:
    handled_errors = (
        RookServiceError,
        RookConfigurationError,
        ValueError,
        TypeError,
        DatabaseError,
        RookWebhookReceipt.DoesNotExist,
        WearableConnection.DoesNotExist,
        LostHealthJobLease,
    )
    try:
        result = process_health_job(job)
    except RookRequestDeferred as error:
        result = {
            "deferred": True,
            "reason": error.reason,
            "retryAfterSeconds": seconds_until(error.retry_at, timezone.localtime()),
        }
        changed = defer_health_job(job, result)
        if changed:
            schedule_retry_wake(job, force=True)
        return {
            "jobId": str(job.pk),
            "status": "deferred" if changed else "superseded",
            **result,
        }
    except handled_errors as error:
        permanent = (
            getattr(error, "status_code", 0) in {400, 401, 403, 404, 422}
            or getattr(error, "terminal", False)
        )
        if fail_health_job(job, error, terminal=permanent):
            schedule_retry_wake(job)
        return {"jobId": str(job.pk), "status": "failed", "detail": str(error)}
    if result.pop("_jobFinalized", False):
        outcome = result.pop("_jobOutcome")
        if outcome == "deferred":
            schedule_retry_wake(job, force=True)
        return {"jobId": str(job.pk), "status": outcome, **result}
    if result.get("authorizationFailed"):
        fail_health_job(job, RuntimeError(result["reason"]), terminal=True)
        return {"jobId": str(job.pk), "status": "failed", **result}
    if result.get("deferred"):
        changed = defer_health_job(job, result)
        if changed:
            schedule_retry_wake(job, force=True)
        outcome = "deferred" if changed else "superseded"
    else:
        changed = complete_health_job(job, result)
        outcome = (
            ("skipped" if result.get("skipped") else "completed")
            if changed
            else "superseded"
        )
    return {"jobId": str(job.pk), "status": outcome, **result}


def process_rook_job_ids(
    job_ids: list[UUID],
    *,
    kind: str,
    queue_url: str = "",
    receipt_handle: str = "",
) -> list[dict]:
    if kind not in {QUEUE_KIND_AUTH, QUEUE_KIND_DATA_FETCH}:
        raise ValueError("ROOK worker kind must be auth or data_fetch.")
    for stale_id in reset_stale_health_jobs():
        schedule_job_wake(stale_id)
    results = []
    if not (kind == QUEUE_KIND_DATA_FETCH and enabled_setting("ROOK_PULLS_PAUSED", False)):
        for job_id in job_ids:
            job = RookOutbox.objects.filter(pk=job_id).first()
            if job is None:
                continue
            if queue_kind(job.job_type) != kind:
                continue
            claimed = claim_health_job(job_id)
            if claimed is None:
                continue
            results.append(run_claimed_health_job(claimed))
    if receipt_handle and queue_url:
        delete_queue_message(
            queue_url=queue_url,
            receipt_handle=receipt_handle,
            log_label=f"ROOK {kind}",
            region=getattr(settings, "AWS_REGION", None),
        )
    return results


def process_pending_rook_outbox(*, kind: str, limit: int = 5) -> list[dict]:
    if kind not in {QUEUE_KIND_AUTH, QUEUE_KIND_DATA_FETCH}:
        raise ValueError("ROOK worker kind must be auth or data_fetch.")
    for stale_id in reset_stale_health_jobs():
        schedule_job_wake(stale_id)
    if kind == QUEUE_KIND_DATA_FETCH and enabled_setting("ROOK_PULLS_PAUSED", False):
        return []
    if limit <= 0:
        return []
    ready = RookOutbox.objects.filter(
        status__in=(HealthJobStatus.PENDING, HealthJobStatus.FAILED),
        scheduled_at__lte=timezone.now(),
    ).filter(rook_outbox_retryable_q())
    if kind == QUEUE_KIND_AUTH:
        ready = ready.exclude(job_type=HealthJobType.FETCH_ROOK_DATA)
    else:
        ready = ready.filter(job_type=HealthJobType.FETCH_ROOK_DATA)
        limit = min(limit, MAXIMUM_FETCH_ROOK_DATA_PER_SWEEP)
    ready = ready.annotate(priority=Case(
        When(job_type=HealthJobType.REVOKE_ROOK_CONNECTION, then=Value(0)),
        When(job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION, then=Value(1)),
        When(job_type=HealthJobType.FETCH_ROOK_DATA, then=Value(2)),
        default=Value(6),
        output_field=IntegerField(),
    )).order_by("priority", "scheduled_at", "pk")
    results = []
    for job_id in list(ready.values_list("pk", flat=True)[:min(max(limit * 5, 10), 50)]):
        if len(results) >= limit:
            break
        job = claim_health_job(job_id)
        if job is None:
            continue
        results.append(run_claimed_health_job(job))
    return results
