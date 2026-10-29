from django.conf import settings
from django.core.management.base import BaseCommand

from accounts.customers.models import CustomerProfile
from wearables.services.job_processor import (
    connections_requiring_recovery_pull,
    enqueue_orphaned_normalization_jobs,
    eligible_freshness_profiles,
)
from wearables.services.oauth import expire_oauth_attempts
from wearables.models import WearableConnection
from wearables.utils.constants import ConnectionStatus
from wearables.services.job_queue import enqueue_or_reuse_freshness_job, enqueue_or_reuse_recovery_job


class Command(BaseCommand):
    help = "Enqueue bounded dashboard freshness checks for active wearable profiles."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--freshness-limit", type=int, default=25,
            help="Maximum new or requeued freshness jobs per sweep (default: 25).",
        )

    def handle(self, *args, **options):
        if not getattr(settings, "WEARABLES_ENABLED", True):
            self.stdout.write("Wearable integration is disabled; no jobs enqueued.")
            return
        # Resolve abandoned OAuth attempts without relying on a user polling
        # GET /devices/. This command must be scheduled by the deployment.
        pending_profile_ids = WearableConnection.objects.filter(
            status__in=(ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING),
        ).values_list("customer_profile_id", flat=True).distinct()
        expired_count = 0
        for profile in CustomerProfile.objects.filter(pk__in=pending_profile_ids).iterator():
            expired_count += expire_oauth_attempts(profile)
        # A stable per-profile key is reused after completion instead of
        # inserting another row every hour. Only oldest eligible profiles are
        # selected; open and recently attempted jobs are skipped in SQL.
        count = 0
        freshness_limit = max(0, min(options["freshness_limit"], 50))
        for customer_profile in eligible_freshness_profiles(limit=freshness_limit).iterator():
            _, queued = enqueue_or_reuse_freshness_job(customer_profile=customer_profile)
            count += int(queued)
        recovery_count = 0
        for connection in connections_requiring_recovery_pull().iterator():
            job, created = enqueue_or_reuse_recovery_job(
                connection=connection, customer_profile=connection.customer_profile,
            )
            if job is not None and created:
                recovery_count += 1
        recovery = enqueue_orphaned_normalization_jobs()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {expired_count} abandoned OAuth attempt(s); "
                f"enqueued {count} freshness check(s), "
                f"{recovery_count} recovery pull(s), "
                f"{recovery['queued']} orphaned normalization(s); "
                f"{recovery['requiresOperatorReview']} document(s) require operator review."
            )
        )

