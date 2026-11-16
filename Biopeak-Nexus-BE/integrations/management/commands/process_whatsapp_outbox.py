from django.core.management.base import BaseCommand, CommandError

from integrations.communications.whatsapp.outbox import (
    process_pending_whatsapp_outbox,
    process_whatsapp_job_ids,
)
from integrations.utils.sqs_job_ids import parse_job_ids, parse_job_ids_from_body


class Command(BaseCommand):
    help = (
        "Process WhatsAppOutbox jobs. Pass --job-ids or --message-body for a "
        "batch, or --limit to drain eligible rows locally."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--job-ids",
            type=str,
            default="",
            help="Comma-separated WhatsAppOutbox UUIDs (max 10 per worker).",
        )
        parser.add_argument(
            "--message-body",
            type=str,
            default="",
            help='JSON SQS body, e.g. {"job_ids":["..."]}.',
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
            "--limit",
            type=int,
            default=50,
            help="When no job ids given, process up to this many eligible rows.",
        )

    def handle(self, *args, **options):
        raw_job_ids = options["job_ids"]
        raw_body = options["message_body"]
        receipt_handle = options["receipt_handle"]
        queue_url = options["queue_url"]
        limit = options["limit"]

        if raw_job_ids and raw_body:
            raise CommandError("Pass only one of --job-ids or --message-body")

        if raw_body:
            job_ids = parse_job_ids_from_body(raw_body)
            results = process_whatsapp_job_ids(
                job_ids,
                queue_url=queue_url,
                receipt_handle=receipt_handle,
            )
        elif raw_job_ids:
            job_ids = parse_job_ids(raw_job_ids)
            results = process_whatsapp_job_ids(
                job_ids,
                queue_url=queue_url,
                receipt_handle=receipt_handle,
            )
        else:
            results = process_pending_whatsapp_outbox(limit=limit)

        self.stdout.write(f"Processed {len(results)} WhatsApp outbox job(s).")
