"""Lightweight reconciliation only; the nightly scheduler owns scheduled pulls."""
from django.core.management.base import BaseCommand

from accounts.customers.models import CustomerProfile
from wearables.models import WearableConnection
from wearables.services.connections import refresh_authorizing_connections
from wearables.services.job_selection import enqueue_orphaned_normalization_jobs
from wearables.services.oauth import expire_oauth_attempts
from wearables.utils.constants import ConnectionStatus


class Command(BaseCommand):
    help = "Reconcile ROOK authorization attempts and orphan QUEUED documents."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--freshness-limit",
            type=int,
            default=5,
            help="Ignored; retained for deploy script compatibility.",
        )

    def handle(self, *args, **options) -> None:
        pending_profiles = WearableConnection.objects.filter(
            status__in=(ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING),
        ).order_by().values("customer_profile_id")
        expired = 0
        for profile in CustomerProfile.objects.filter(pk__in=pending_profiles).order_by("pk")[:100].iterator():
            expired += expire_oauth_attempts(profile)
            refresh_authorizing_connections(profile)
        recovery = enqueue_orphaned_normalization_jobs(limit=25)
        self.stdout.write(
            f"Expired {expired} authorization attempt(s); processed "
            f"{recovery['queued']} orphan document(s) inline "
            f"({recovery['requiresOperatorReview']} need review). "
            f"Scheduled data pulls are queued at midnight."
        )
