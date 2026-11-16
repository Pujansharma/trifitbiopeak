from uuid import UUID

from django.conf import settings

from integrations.utils.constants import GOOGLE_CALENDAR_DISPATCH_BATCH_SIZE
from integrations.utils.sqs_dispatch import delete_queue_message, publish_job_batches


def google_calendar_outbox_queue_url() -> str:
    return getattr(settings, "GOOGLE_CALENDAR_OUTBOX_QUEUE_URL", None) or ""


def google_calendar_outbox_region():
    return getattr(settings, "AWS_REGION", None)


def publish_google_calendar_job_batches(job_ids: list[UUID]) -> list[UUID]:
    """
    Publish one SQS message per non-empty batch of ≤10 ids.
    Returns job ids from batches that SQS accepted. No-op when queue URL unset.
    """
    return publish_job_batches(
        job_ids,
        queue_url=google_calendar_outbox_queue_url(),
        message_group_id="google-calendar-outbox",
        log_label="Google Calendar",
        batch_size=GOOGLE_CALENDAR_DISPATCH_BATCH_SIZE,
        region=google_calendar_outbox_region(),
    )


def delete_google_calendar_queue_message(*, queue_url: str, receipt_handle: str) -> None:
    delete_queue_message(
        queue_url=queue_url,
        receipt_handle=receipt_handle,
        log_label="Google Calendar",
        region=google_calendar_outbox_region(),
    )
