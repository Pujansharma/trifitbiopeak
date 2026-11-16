from datetime import timedelta
from uuid import UUID

from django.db.models import F
from django.utils import timezone

from integrations.models import ProtocolAiOutbox
from integrations.protocol_management.dispatch import (
    delete_protocol_ai_queue_message,
    protocol_ai_outbox_queue_url,
    publish_protocol_ai_job_batches,
)
from integrations.utils.constants import (
    MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS,
    STALE_PROTOCOL_AI_OUTBOX_QUEUED_MINUTES,
    STALE_PROTOCOL_AI_OUTBOX_SENDING_MINUTES,
    ProtocolAiOutboxStatus,
)
from integrations.utils.sqs_dispatch import chunk_job_ids
from supplementation.models import ProtocolAiJob
from supplementation.utils.constants import ProtocolAiJobStatus
from supplementation.utils.protocol_ai import (
    process_protocol_ai_job_until_settled,
    reclaim_stale_protocol_ai_jobs,
)

# Max outbox attempts = 1: PENDING/QUEUED only. FAILED is terminal (no SQS retry).
CLAIMABLE_STATUSES = (
    ProtocolAiOutboxStatus.PENDING,
    ProtocolAiOutboxStatus.QUEUED,
)

DISPATCHABLE_STATUSES = (ProtocolAiOutboxStatus.PENDING,)


def enqueue_protocol_ai_outbox(job: ProtocolAiJob) -> ProtocolAiOutbox:
    existing = ProtocolAiOutbox.objects.filter(job=job).first()
    if existing is not None:
        return existing
    return ProtocolAiOutbox.objects.create(
        job=job,
        status=ProtocolAiOutboxStatus.PENDING,
    )


def publish_protocol_ai_wake(job_id: UUID) -> None:
    """on_commit wake after ProtocolAiJob create — dispatch outbox row to SQS."""
    outbox = ProtocolAiOutbox.objects.filter(job_id=job_id).first()
    if outbox is None:
        return
    dispatch_if_claimable(outbox)


def reclaim_stale_protocol_ai_outbox() -> None:
    now = timezone.localtime()
    sending_cutoff = now - timedelta(minutes=STALE_PROTOCOL_AI_OUTBOX_SENDING_MINUTES)
    queued_cutoff = now - timedelta(minutes=STALE_PROTOCOL_AI_OUTBOX_QUEUED_MINUTES)
    ProtocolAiOutbox.objects.filter(
        status=ProtocolAiOutboxStatus.SENDING,
        updated_at__lt=sending_cutoff,
    ).update(
        status=ProtocolAiOutboxStatus.FAILED,
        error_detail="Stale SENDING reclaimed",
        failed_at=now,
        updated_at=now,
    )
    ProtocolAiOutbox.objects.filter(
        status=ProtocolAiOutboxStatus.QUEUED,
        updated_at__lt=queued_cutoff,
    ).update(
        status=ProtocolAiOutboxStatus.PENDING,
        updated_at=now,
    )


def eligible_protocol_ai_outbox_ids(*, limit: int = 50) -> list[UUID]:
    return list(
        ProtocolAiOutbox.objects.filter(
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )


def mark_protocol_ai_outbox_queued(job_ids: list[UUID]) -> list[UUID]:
    now = timezone.localtime()
    marked = []
    for job_id in job_ids:
        updated = ProtocolAiOutbox.objects.filter(
            pk=job_id,
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS,
        ).update(
            status=ProtocolAiOutboxStatus.QUEUED,
            updated_at=now,
        )
        if updated == 1:
            marked.append(job_id)
    return marked


def revert_protocol_ai_outbox_to_pending(job_ids: list[UUID]) -> int:
    if not job_ids:
        return 0
    now = timezone.localtime()
    return ProtocolAiOutbox.objects.filter(
        pk__in=job_ids,
        status=ProtocolAiOutboxStatus.QUEUED,
    ).update(
        status=ProtocolAiOutboxStatus.PENDING,
        updated_at=now,
    )


def dispatch_protocol_ai_outbox_ids(job_ids: list[UUID]) -> int:
    if not protocol_ai_outbox_queue_url():
        return 0
    marked_ids = mark_protocol_ai_outbox_queued(job_ids)
    if not marked_ids:
        return 0
    published_ids = publish_protocol_ai_job_batches(marked_ids)
    published_set = set(published_ids)
    unpublished_ids = [
        job_id for job_id in marked_ids if job_id not in published_set
    ]
    if unpublished_ids:
        revert_protocol_ai_outbox_to_pending(unpublished_ids)
    if not published_ids:
        return 0
    return sum(1 for _ in chunk_job_ids(published_ids))


def dispatch_if_claimable(message: ProtocolAiOutbox) -> None:
    if message.status not in DISPATCHABLE_STATUSES:
        return
    if message.attempt_count >= MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS:
        return
    dispatch_protocol_ai_outbox_ids([message.pk])


def dispatch_eligible_protocol_ai_jobs(*, limit: int = 50) -> int:
    reclaim_stale_protocol_ai_outbox()
    reclaim_stale_protocol_ai_jobs()
    return dispatch_protocol_ai_outbox_ids(
        eligible_protocol_ai_outbox_ids(limit=limit)
    )


def claim_protocol_ai_outbox(message_id: UUID) -> ProtocolAiOutbox | None:
    updated = ProtocolAiOutbox.objects.filter(
        pk=message_id,
        status__in=CLAIMABLE_STATUSES,
        attempt_count__lt=MAX_PROTOCOL_AI_OUTBOX_ATTEMPTS,
    ).update(
        status=ProtocolAiOutboxStatus.SENDING,
        attempt_count=F("attempt_count") + 1,
        error_detail="",
        skip_reason="",
        updated_at=timezone.localtime(),
    )
    if updated != 1:
        return None
    return (
        ProtocolAiOutbox.objects.select_related("job")
        .filter(pk=message_id)
        .first()
    )


def finish_protocol_ai_outbox(message: ProtocolAiOutbox, job: ProtocolAiJob) -> None:
    now = timezone.localtime()
    if job.status == ProtocolAiJobStatus.COMPLETED:
        ProtocolAiOutbox.objects.filter(
            pk=message.pk,
            status=ProtocolAiOutboxStatus.SENDING,
        ).update(
            status=ProtocolAiOutboxStatus.ACCEPTED,
            accepted_at=now,
            error_detail="",
            updated_at=now,
        )
        return
    if job.status == ProtocolAiJobStatus.FAILED:
        ProtocolAiOutbox.objects.filter(
            pk=message.pk,
            status=ProtocolAiOutboxStatus.SENDING,
        ).update(
            status=ProtocolAiOutboxStatus.FAILED,
            failed_at=now,
            error_detail=job.error_detail[:2000],
            updated_at=now,
        )
        return
    # Soft miss (job not claimable, e.g. still PROCESSING) — refund attempt
    # the same way stale PROCESSING jobs refund attempt_count.
    ProtocolAiOutbox.objects.filter(
        pk=message.pk,
        status=ProtocolAiOutboxStatus.SENDING,
    ).update(
        status=ProtocolAiOutboxStatus.PENDING,
        attempt_count=F("attempt_count") - 1,
        error_detail="",
        updated_at=now,
    )


def mark_protocol_ai_outbox_skipped_missing_job(message: ProtocolAiOutbox) -> ProtocolAiOutbox:
    now = timezone.localtime()
    ProtocolAiOutbox.objects.filter(pk=message.pk).update(
        status=ProtocolAiOutboxStatus.SKIPPED,
        skip_reason="ProtocolAiJob missing",
        updated_at=now,
    )
    message.refresh_from_db()
    return message


def process_protocol_ai_outbox_message(message: ProtocolAiOutbox) -> ProtocolAiOutbox:
    """One outbox claim. Job try + retry lives on ProtocolAiJob."""
    reclaim_stale_protocol_ai_jobs()
    job = process_protocol_ai_job_until_settled(message.job_id)
    if job is None:
        return mark_protocol_ai_outbox_skipped_missing_job(message)
    finish_protocol_ai_outbox(message, job)
    message.refresh_from_db()
    return message


def process_protocol_ai_outbox_by_id(message_id: UUID) -> ProtocolAiOutbox | None:
    claimed = claim_protocol_ai_outbox(message_id)
    if claimed is None:
        return ProtocolAiOutbox.objects.filter(pk=message_id).first()
    return process_protocol_ai_outbox_message(claimed)


def process_protocol_ai_job_ids(
    job_ids: list[UUID],
    *,
    queue_url: str = "",
    receipt_handle: str = "",
) -> list[ProtocolAiOutbox | None]:
    reclaim_stale_protocol_ai_outbox()
    results = [process_protocol_ai_outbox_by_id(job_id) for job_id in job_ids]
    if receipt_handle and queue_url:
        delete_protocol_ai_queue_message(
            queue_url=queue_url,
            receipt_handle=receipt_handle,
        )
    return results


def process_pending_protocol_ai_outbox(*, limit: int = 50):
    reclaim_stale_protocol_ai_outbox()
    job_ids = eligible_protocol_ai_outbox_ids(limit=limit)
    return process_protocol_ai_job_ids(job_ids)
