from uuid import UUID

from django.core.management.base import BaseCommand, CommandError

from integrations.protocol_management.outbox import (
    process_pending_protocol_ai_outbox,
    process_protocol_ai_job_ids,
)
from integrations.utils.sqs_job_ids import parse_job_ids, parse_job_ids_from_body
from supplementation.utils.protocol_ai import (
    UUID_TEXT_PATTERN,
    process_pending_protocol_ai_jobs,
)


class Command(BaseCommand):
    help = (
        "Process ProtocolAiOutbox jobs. Pass --job-ids or --message-body for a "
        "batch of outbox ids, --limit to drain the outbox, or --job-id for a "
        "single ProtocolAiJob (local)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job-ids",
            type=str,
            default="",
            help="Comma-separated ProtocolAiOutbox UUIDs (max 10 per worker).",
        )
        parser.add_argument(
            "--message-body",
            type=str,
            default="",
            help='JSON SQS body, e.g. {"job_ids":["..."]} (outbox ids).',
        )
        parser.add_argument(
            "--receipt-handle",
            type=str,
            default="",
            help="SQS receipt handle; deleted after orderly processing.",
        )
        parser.add_argument(
            "--queue-url",
            type=str,
            default="",
            help="SQS queue URL used with --receipt-handle.",
        )
        parser.add_argument(
            "--job-id",
            default="",
            help="Process this ProtocolAiJob only (local / legacy).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="When no ids given, process up to this many outbox rows.",
        )

    def handle(self, *args, **options):
        raw_job_ids = options["job_ids"]
        raw_body = options["message_body"]
        receipt_handle = options["receipt_handle"]
        queue_url = options["queue_url"]
        limit = options["limit"]
        legacy_job_id = options["job_id"].strip()

        if raw_job_ids and raw_body:
            raise CommandError("Pass only one of --job-ids or --message-body")
        if (raw_job_ids or raw_body) and legacy_job_id:
            raise CommandError("Pass only one of --job-id or batch options")

        if raw_body:
            job_ids = parse_job_ids_from_body(raw_body)
            results = process_protocol_ai_job_ids(
                job_ids,
                queue_url=queue_url,
                receipt_handle=receipt_handle,
            )
            processed = len([row for row in results if row is not None])
        elif raw_job_ids:
            job_ids = parse_job_ids(raw_job_ids)
            results = process_protocol_ai_job_ids(
                job_ids,
                queue_url=queue_url,
                receipt_handle=receipt_handle,
            )
            processed = len([row for row in results if row is not None])
        elif legacy_job_id:
            if UUID_TEXT_PATTERN.fullmatch(legacy_job_id) is None:
                raise CommandError("Invalid job id.")
            results = process_pending_protocol_ai_jobs(job_id=UUID(legacy_job_id))
            processed = len([job_id for job_id in results if job_id is not None])
        else:
            results = process_pending_protocol_ai_outbox(limit=limit)
            processed = len([row for row in results if row is not None])

        self.stdout.write(
            self.style.SUCCESS(f"Processed {processed} protocol AI job(s).")
        )
