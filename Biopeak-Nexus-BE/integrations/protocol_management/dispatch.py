from uuid import UUID

from django.conf import settings

from integrations.utils.constants import PROTOCOL_AI_DISPATCH_BATCH_SIZE
from integrations.utils.sqs_dispatch import delete_queue_message, publish_job_batches


def protocol_ai_outbox_queue_url() -> str:
    return getattr(settings, "PROTOCOL_AI_OUTBOX_QUEUE_URL", None) or ""


def protocol_ai_outbox_region():
    return getattr(settings, "AWS_REGION", None)


def publish_protocol_ai_job_batches(job_ids: list[UUID]) -> list[UUID]:
    """
    Publish one SQS message per non-empty batch of ≤10 ids.
    Returns job ids from batches that SQS accepted. No-op when queue URL unset.
    """
    return publish_job_batches(
        job_ids,
        queue_url=protocol_ai_outbox_queue_url(),
        message_group_id="protocol-ai-outbox",
        log_label="protocol AI",
        batch_size=PROTOCOL_AI_DISPATCH_BATCH_SIZE,
        region=protocol_ai_outbox_region(),
    )


def delete_protocol_ai_queue_message(*, queue_url: str, receipt_handle: str) -> None:
    delete_queue_message(
        queue_url=queue_url,
        receipt_handle=receipt_handle,
        log_label="protocol AI",
        region=protocol_ai_outbox_region(),
    )
