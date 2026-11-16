"""SQS wake batches for ROOK jobs; PostgreSQL rows stay authoritative.

Send after commit. A failed publish leaves wake_version > wake_sent_version.
Workers process `job_ids` batches (≤10), same shape as WA/GC/AI.
"""
from datetime import timedelta
from functools import partial
from uuid import UUID

from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from integrations.utils.constants import OUTBOX_WORKER_JOB_IDS_MAX
from integrations.utils.sqs_dispatch import publish_job_batches
from wearables.models import RookOutbox
from wearables.services.runtime import setting
from wearables.services.job_claims import rook_outbox_retryable_q
from wearables.utils.constants import HealthJobStatus, HealthJobType

QUEUE_KIND_AUTH = "auth"
QUEUE_KIND_DATA_FETCH = "data_fetch"
QUEUE_SETTING_BY_KIND = {
    QUEUE_KIND_AUTH: "ROOK_AUTH_OUTBOX_QUEUE_URL",
    QUEUE_KIND_DATA_FETCH: "ROOK_DATA_FETCH_OUTBOX_QUEUE_URL",
}
QUEUE_MESSAGE_GROUP_BY_KIND = {
    QUEUE_KIND_AUTH: "rook-auth",
    QUEUE_KIND_DATA_FETCH: "rook-data-fetch",
}


def queue_kind(job_type: str) -> str:
    if job_type == HealthJobType.FETCH_ROOK_DATA:
        return QUEUE_KIND_DATA_FETCH
    return QUEUE_KIND_AUTH


def queue_url(kind: str) -> str:
    setting_name = QUEUE_SETTING_BY_KIND.get(kind)
    if setting_name is None:
        raise ValueError("Invalid ROOK queue kind.")
    return str(setting(setting_name, "") or "")


def eligible_wake_jobs(kind: str | None = None):
    now = timezone.localtime()
    query = RookOutbox.objects.filter(
        status__in=(HealthJobStatus.PENDING, HealthJobStatus.FAILED),
        scheduled_at__lte=now,
        wake_version__gt=F("wake_sent_version"),
    ).filter(rook_outbox_retryable_q()).filter(
        Q(wake_next_attempt_at__isnull=True) | Q(wake_next_attempt_at__lte=now)
    )
    if kind == QUEUE_KIND_DATA_FETCH:
        query = query.filter(job_type=HealthJobType.FETCH_ROOK_DATA)
    elif kind == QUEUE_KIND_AUTH:
        query = query.exclude(job_type=HealthJobType.FETCH_ROOK_DATA)
    return query.order_by("scheduled_at", "pk")


def publish_job_wake_batch(job_ids: list[UUID], *, kind: str) -> list[UUID]:
    if not job_ids:
        return []
    url = queue_url(kind)
    if not url:
        return []
    jobs = list(eligible_wake_jobs(kind).filter(pk__in=job_ids))
    if not jobs:
        return []
    versions = {job.pk: job.wake_version for job in jobs}
    published = publish_job_batches(
        [job.pk for job in jobs],
        queue_url=url,
        message_group_id=QUEUE_MESSAGE_GROUP_BY_KIND[kind],
        log_label=f"ROOK {kind}",
        batch_size=OUTBOX_WORKER_JOB_IDS_MAX,
        region=setting("AWS_REGION", "ap-south-1") or "ap-south-1",
    )
    if not published:
        retry_at = timezone.localtime() + timedelta(seconds=30)
        for job_id, version in versions.items():
            RookOutbox.objects.filter(pk=job_id, wake_version=version).update(
                wake_next_attempt_at=retry_at,
            )
        return []
    for job_id in published:
        version = versions.get(job_id)
        if version is None:
            continue
        RookOutbox.objects.filter(pk=job_id, wake_version=version).update(
            wake_sent_version=version, wake_next_attempt_at=None,
        )
    return published


def publish_job_wake(job_id) -> bool:
    job = eligible_wake_jobs().filter(pk=job_id).first()
    if job is None:
        return False
    return bool(publish_job_wake_batch([job.pk], kind=queue_kind(job.job_type)))


def schedule_job_wake(job_id):
    transaction.on_commit(partial(publish_job_wake, job_id), robust=True)


def mark_job_wake_pending(job_id):
    RookOutbox.objects.filter(pk=job_id).update(
        wake_version=F("wake_version") + 1, wake_next_attempt_at=None,
    )
    schedule_job_wake(job_id)
