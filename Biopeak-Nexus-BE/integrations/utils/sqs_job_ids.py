import json
from uuid import UUID

from django.core.management.base import CommandError

from integrations.utils.constants import OUTBOX_WORKER_JOB_IDS_MAX


def parse_job_ids(raw_job_ids: str) -> list[UUID]:
    values = [part.strip() for part in raw_job_ids.split(",") if part.strip()]
    if not values:
        raise CommandError("job_ids must be a non-empty list")
    if len(values) > OUTBOX_WORKER_JOB_IDS_MAX:
        raise CommandError(
            f"job_ids must contain at most {OUTBOX_WORKER_JOB_IDS_MAX} ids"
        )
    return [UUID(value) for value in values]


def parse_job_ids_from_body(raw_body: str) -> list[UUID]:
    payload = json.loads(raw_body)
    if not isinstance(payload, dict):
        raise CommandError("SQS body must be a JSON object with job_ids")
    raw_ids = payload.get("job_ids") or []
    if not isinstance(raw_ids, list) or not raw_ids:
        raise CommandError("SQS body job_ids must be a non-empty list")
    if len(raw_ids) > OUTBOX_WORKER_JOB_IDS_MAX:
        raise CommandError(
            f"SQS body job_ids must contain at most {OUTBOX_WORKER_JOB_IDS_MAX} ids"
        )
    return [UUID(str(value)) for value in raw_ids]
