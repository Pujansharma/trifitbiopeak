from django.conf import settings
from django.core.management.base import BaseCommand

from wearables.services.job_processor import process_pending_health_jobs


class Command(BaseCommand):
    help = "Process pending and retryable wearable health jobs."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Maximum health jobs to process in this run.",
        )
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument(
            "--skip-recovery", action="store_true",
            help="Do not run long ROOK recovery pulls in the shared sweep.",
        )
        mode.add_argument(
            "--only-recovery", action="store_true",
            help="Process recovery pulls only (in a separately scheduled worker).",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "WEARABLES_ENABLED", False):
            self.stdout.write("Wearable integration is disabled; no jobs processed.")
            return
        results = process_pending_health_jobs(
            limit=options["limit"],
            skip_recovery=options["skip_recovery"],
            only_recovery=options["only_recovery"],
        )
        self.stdout.write(
            self.style.SUCCESS(f"Processed {len(results)} wearable health job(s).")
        )

