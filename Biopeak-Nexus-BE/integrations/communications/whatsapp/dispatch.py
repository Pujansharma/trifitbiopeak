from uuid import UUID

from django.conf import settings

from integrations.utils.constants import WHATSAPP_DISPATCH_BATCH_SIZE
from integrations.utils.sqs_dispatch import delete_queue_message, publish_job_batches


def whatsapp_outbox_queue_url() -> str:
    return getattr(settings, "WHATSAPP_OUTBOX_QUEUE_URL", None) or ""


def whatsapp_outbox_region():
    return getattr(settings, "AWS_REGION", None)


def publish_whatsapp_job_batches(job_ids: list[UUID]) -> list[UUID]:
    """
    Publish one SQS message per non-empty batch of ≤10 ids.
    Returns job ids from batches that SQS accepted. No-op (empty list) when
    queue URL unset.
    """
    return publish_job_batches(
        job_ids,
        queue_url=whatsapp_outbox_queue_url(),
        message_group_id="whatsapp-outbox",
        log_label="WhatsApp",
        batch_size=WHATSAPP_DISPATCH_BATCH_SIZE,
        region=whatsapp_outbox_region(),
    )


def delete_whatsapp_queue_message(*, queue_url: str, receipt_handle: str) -> None:
    delete_queue_message(
        queue_url=queue_url,
        receipt_handle=receipt_handle,
        log_label="WhatsApp",
        region=whatsapp_outbox_region(),
    )
