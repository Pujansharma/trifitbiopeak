from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from core.utils.log import logger

WAKE_COMMAND = "process_protocol_ai_jobs"
WAKE_MESSAGE_GROUP_ID = "protocol-ai-jobs"


def protocol_ai_wake_queue_url():
    return getattr(settings, "PROTOCOL_AI_WAKE_QUEUE_URL", None) or ""


def protocol_ai_wake_region():
    return getattr(settings, "AWS_REGION", None)


def is_fifo_queue(queue_url):
    return queue_url.endswith(".fifo")


def wake_message_deduplication_id(job_id: UUID) -> str:
    return str(job_id)


def wake_message_body(job_id: UUID):
    return f"{WAKE_COMMAND} --job-id {job_id}"


def publish_protocol_ai_wake(job_id: UUID) -> None:
    queue_url = protocol_ai_wake_queue_url()
    if not queue_url:
        return
    request = {
        "QueueUrl": queue_url,
        "MessageBody": wake_message_body(job_id),
    }
    if is_fifo_queue(queue_url):
        request["MessageGroupId"] = WAKE_MESSAGE_GROUP_ID
        request["MessageDeduplicationId"] = wake_message_deduplication_id(job_id)
    try:
        client = boto3.client("sqs", region_name=protocol_ai_wake_region())
        client.send_message(**request)
    except (BotoCoreError, ClientError) as error:
        logger.warning(f"Failed to publish protocol AI wake: {error}")
