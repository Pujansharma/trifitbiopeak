from django.core.management.base import BaseCommand

from integrations.protocol_management.outbox import dispatch_eligible_protocol_ai_jobs


class Command(BaseCommand):
    help = (
        "Protocol AI scheduled entrypoint: reclaim stale PROCESSING jobs and "
        "dispatch eligible ProtocolAiJob rows to SQS (EventBridge schedule; "
        "mirrors run_whatsapp_reminder_schedule)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max ProtocolAiJob rows to dispatch this run.",
        )

    def handle(self, *args, **options):
        published = dispatch_eligible_protocol_ai_jobs(limit=options["limit"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {published} protocol AI SQS batch(es)."
            )
        )
