from django.core.management.base import BaseCommand

from integrations.communications.service import enqueue_due_appointment_reminders
from integrations.communications.whatsapp.outbox import dispatch_eligible_whatsapp_jobs


class Command(BaseCommand):
    help = (
        "Enqueue due WhatsApp appointment reminders and dispatch claimable "
        "WhatsAppOutbox jobs to SQS (EventBridge schedule entrypoint)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max reminder rows to enqueue and max jobs to dispatch.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        reminders = enqueue_due_appointment_reminders(limit=limit)
        published = dispatch_eligible_whatsapp_jobs(limit=limit)
        self.stdout.write(
            f"Enqueued {len(reminders)} reminder(s); published {published} SQS batch(es)."
        )
