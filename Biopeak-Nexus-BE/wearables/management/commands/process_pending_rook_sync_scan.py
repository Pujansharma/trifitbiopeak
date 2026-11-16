from django.core.management.base import BaseCommand, CommandError

from wearables.services.scheduling import run_rook_sync_scan


class Command(BaseCommand):
    help = (
        "Once at local midnight, enqueue fetch_rook_data for connections "
        "with missing or >=7-day-old sync coverage."
    )

    def handle(self, *args, **options) -> None:
        try:
            result = run_rook_sync_scan()
        except ValueError as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            f"ROOK sync scan runDate={result.get('runDate')}: "
            f"enqueued={result.get('enqueuedCount', 0)}; "
            f"deferred={bool(result.get('deferred'))}."
        )
