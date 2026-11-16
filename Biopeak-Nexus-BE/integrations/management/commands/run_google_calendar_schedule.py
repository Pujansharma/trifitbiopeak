from django.core.management.base import BaseCommand

from integrations.google_calendar.outbox import dispatch_eligible_google_calendar_jobs
from integrations.google_calendar.webhook_channel import (
    renew_expiring_google_calendar_watch_channels,
)


class Command(BaseCommand):
    help = (
        "Google Calendar scheduled entrypoint: reclaim/dispatch "
        "GoogleCalendarOutbox jobs to SQS and renew personal watch channels "
        "(EventBridge schedule; mirrors run_whatsapp_reminder_schedule)."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max GoogleCalendarOutbox jobs to dispatch this run.",
        )

    def handle(self, *args, **options):
        published = dispatch_eligible_google_calendar_jobs(limit=options["limit"])
        renewed, failed = renew_expiring_google_calendar_watch_channels()
        self.stdout.write(
            self.style.SUCCESS(
                f"Published {published} Google Calendar SQS batch(es); "
                f"renewed {renewed} watch channel(s); {failed} renewal(s) failed."
            )
        )
