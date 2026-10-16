from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.customers.models import CustomerProfile
from wearables.services.job_processor import (
    connections_requiring_recovery_pull,
    enqueue_orphaned_normalization_jobs,
    profiles_requiring_freshness_check,
)
from wearables.services.oauth import expire_oauth_attempts
from wearables.models import WearableConnection
from wearables.utils.constants import ConnectionStatus
from wearables.services.job_queue import enqueue_health_job
from wearables.utils.constants import HealthJobType


class Command(BaseCommand):
    help = "Enqueue dashboard freshness checks for active wearable profiles."

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
        profile_ids = list(profiles_requiring_freshness_check())
        profiles = CustomerProfile.objects.filter(pk__in=profile_ids)
        # Re-check every scheduler hour; a daily idempotency key would suppress
        # all later freshness and recovery checks even after new data arrives.
        date_key = timezone.now().strftime("%Y-%m-%dT%H")
        count = 0
        for customer_profile in profiles.iterator():
            enqueue_health_job(
                job_type=HealthJobType.FRESHNESS_CHECK,
                idempotency_key=f"freshness:{customer_profile.pk}:{date_key}",
                customer_profile=customer_profile,
            )
            count += 1
        recovery_count = 0
        for connection in connections_requiring_recovery_pull().iterator():
            enqueue_health_job(
                job_type=HealthJobType.RECOVERY_PULL,
                idempotency_key=f"recovery:{connection.pk}:{date_key}",
                customer_profile=connection.customer_profile,
                connection=connection,
            )
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

