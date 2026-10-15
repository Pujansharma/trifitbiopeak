from django.conf import settings
from django.core.management.base import CommandError
import uuid
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

        parser.add_argument(
            "--customer-profile-id",
            type=uuid.UUID,
            default=None,
            help="Optional UUID: select only jobs belonging to this customer profile.",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "WEARABLES_ENABLED", True):
            self.stdout.write("Wearable integration is disabled; no jobs processed.")
            return
        if options["limit"] < 1:
            raise CommandError("--limit must be at least 1")
        results = process_pending_health_jobs(
            limit=options["limit"],
            customer_profile_id=options["customer_profile_id"],
        )
        completed = sum(result.get("status") == "completed" for result in results)
        failed = sum(result.get("status") == "failed" for result in results)
        self.stdout.write(
            self.style.SUCCESS(
                f"Handled {len(results)} wearable health job(s): "
                f"{completed} completed, {failed} failed."
            )
        )

