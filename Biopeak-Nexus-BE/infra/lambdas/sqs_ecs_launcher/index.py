"""
SQS → ECS Fargate launcher.

On successful RunTask the Lambda event-source mapping deletes the SQS message.
Job durability then lives in WhatsAppOutbox (QUEUED/SENDING) + cron re-dispatch.
Do not treat RunTask acceptance as Meta send success.
"""

from __future__ import annotations

import json
import os

import boto3

ecs = boto3.client("ecs")

CLUSTER_ARN = os.environ["CLUSTER_ARN"]
TASK_DEFINITION_ARN = os.environ["TASK_DEFINITION_ARN"]
SUBNET_IDS = [value for value in os.environ.get("SUBNET_IDS", "").split(",") if value]
SECURITY_GROUP_IDS = [
    value for value in os.environ.get("SECURITY_GROUP_IDS", "").split(",") if value
]
CONTAINER_NAME = os.environ.get("CONTAINER_NAME", "backend")
WORKER_COMMAND = os.environ.get("WORKER_COMMAND", "process_whatsapp_outbox")
ASSIGN_PUBLIC_IP = os.environ.get("ASSIGN_PUBLIC_IP", "DISABLED")
QUEUE_URL = os.environ.get("QUEUE_URL", "")
# Keep in sync with integrations.utils.constants.OUTBOX_WORKER_JOB_IDS_MAX
MAX_JOB_IDS = 10


def _message_has_valid_job_ids(body: str) -> bool:
    payload = json.loads(body)
    job_ids = payload.get("job_ids") if isinstance(payload, dict) else None
    return isinstance(job_ids, list) and 0 < len(job_ids) <= MAX_JOB_IDS


def _run_worker_task(*, message_body: str, queue_url: str, receipt_handle: str) -> str:
    command = [
        "python",
        "manage.py",
        WORKER_COMMAND,
        "--message-body",
        message_body,
        "--queue-url",
        queue_url,
        "--receipt-handle",
        receipt_handle,
    ]
    response = ecs.run_task(
        cluster=CLUSTER_ARN,
        taskDefinition=TASK_DEFINITION_ARN,
        launchType="FARGATE",
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": SUBNET_IDS,
                "securityGroups": SECURITY_GROUP_IDS,
                "assignPublicIp": ASSIGN_PUBLIC_IP,
            }
        },
        overrides={
            "containerOverrides": [
                {
                    "name": CONTAINER_NAME,
                    "command": command,
                }
            ]
        },
    )
    failures = response.get("failures") or []
    if failures:
        raise RuntimeError(f"ecs.RunTask failures: {failures}")
    tasks = response.get("tasks") or []
    if not tasks:
        raise RuntimeError("ecs.RunTask returned no tasks")
    return tasks[0]["taskArn"]


def handler(event, _context):
    batch_item_failures = []
    for record in event.get("Records") or []:
        message_id = record.get("messageId") or ""
        try:
            body = record["body"]
            if not _message_has_valid_job_ids(body):
                raise ValueError(
                    f"SQS body must include 1..{MAX_JOB_IDS} job_ids"
                )
            _run_worker_task(
                message_body=body,
                queue_url=QUEUE_URL,
                receipt_handle=record.get("receiptHandle") or "",
            )
        except Exception:
            if message_id:
                batch_item_failures.append({"itemIdentifier": message_id})
            else:
                raise
    return {"batchItemFailures": batch_item_failures}
