from django.core.management.base import BaseCommand

from integrations.google_calendar.webhook_channel import (
    renew_expiring_google_calendar_watch_channels,
)


class Command(BaseCommand):
    help = (
        "Renew personal Google Calendar notification channels that are "
        "close to expiring. Prefer run_google_calendar_schedule on EventBridge; "
        "this command remains for manual runs."
    )

    def handle(self, *args, **options):
        renewed, failed = renew_expiring_google_calendar_watch_channels()
        self.stdout.write(
            self.style.SUCCESS(
                f"Renewed {renewed} Google Calendar watch channel(s); {failed} failed."
            )
        )
