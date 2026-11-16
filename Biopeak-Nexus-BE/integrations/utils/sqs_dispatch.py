import hashlib
import json
from uuid import UUID

import boto3
from botocore.exceptions import BotoCoreError, ClientError
from django.conf import settings

from core.utils.log import logger
from integrations.utils.constants import OUTBOX_WORKER_JOB_IDS_MAX


def aws_region():
    return getattr(settings, "AWS_REGION", None)


def is_fifo_queue(queue_url: str) -> bool:
    return queue_url.endswith(".fifo")


def fifo_message_deduplication_id(job_ids: list[UUID]) -> str:
    """SQS FIFO dedup id max 128 chars — hash the batch, never join raw UUIDs."""
    joined = "-".join(str(job_id) for job_id in job_ids)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def chunk_job_ids(
    job_ids: list[UUID],
    *,
    batch_size: int = OUTBOX_WORKER_JOB_IDS_MAX,
):
    if batch_size < 1:
        raise ValueError("batch_size must be >= 1")
    unique_ids = []
    seen = set()
    for job_id in job_ids:
        if job_id in seen:
            continue
        seen.add(job_id)
        unique_ids.append(job_id)
    for index in range(0, len(unique_ids), batch_size):
        batch = unique_ids[index : index + batch_size]
        if batch:
            yield batch


def message_body_for_job_ids(job_ids: list[UUID]) -> str:
    return json.dumps({"job_ids": [str(job_id) for job_id in job_ids]})


def publish_job_batches(
    job_ids: list[UUID],
    *,
    queue_url: str,
    message_group_id: str,
    log_label: str,
    batch_size: int = OUTBOX_WORKER_JOB_IDS_MAX,
    region=None,
) -> list[UUID]:
    """
    Publish one SQS message per non-empty batch.
    Returns job ids from batches that SQS accepted. No-op when queue URL unset.
    """
    if not queue_url:
        return []
    batches = list(chunk_job_ids(job_ids, batch_size=batch_size))
    if not batches:
        return []
    client = boto3.client(
        "sqs",
        region_name=aws_region() if region is None else region,
    )
    published_ids = []
    for batch in batches:
        request = {
            "QueueUrl": queue_url,
            "MessageBody": message_body_for_job_ids(batch),
        }
        if is_fifo_queue(queue_url):
            request["MessageGroupId"] = message_group_id
            request["MessageDeduplicationId"] = fifo_message_deduplication_id(batch)
        try:
            client.send_message(**request)
            published_ids.extend(batch)
        except (BotoCoreError, ClientError) as error:
            logger.warning(f"Failed to publish {log_label} outbox batch: {error}")
    return published_ids


def delete_queue_message(
    *,
    queue_url: str,
    receipt_handle: str,
    log_label: str,
    region=None,
) -> None:
    if not queue_url or not receipt_handle:
        return
    try:
        client = boto3.client(
            "sqs",
            region_name=aws_region() if region is None else region,
        )
        client.delete_message(QueueUrl=queue_url, ReceiptHandle=receipt_handle)
    except (BotoCoreError, ClientError) as error:
        logger.warning(f"Failed to delete {log_label} outbox SQS message: {error}")
