"""Read-only ROOK release preflight; does not generate/apply migrations or call AWS."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection
from django.db.models import Count

from wearables.models import RookOutbox, RookRequestBudget, WearableConnection
from wearables.services.runtime import recovery_units_per_slice, request_limits
from wearables.utils.constants import HealthJobStatus, HealthJobType


class Command(BaseCommand):
    help = "Read-only configuration/schema preflight. Does not certify provider, AWS or load-test readiness."

    def handle(self, *args, **options):
        errors = []
        if connection.vendor != "postgresql":
            errors.append("PostgreSQL is required for the production worker coordination tests.")
        try:
            request_limits()
            recovery_units_per_slice()
        except (ValueError, TypeError) as error:
            errors.append(str(error))
        try:
            WearableConnection.objects.values(
                "last_manual_sync_queued_at",
                "pending_sync_requested_at",
                "last_data_processed_at",
                "synced_through",
                "authorization_generation",
                "last_sync_requested_at",
                "last_pull_completed_at",
            ).first()
            RookOutbox.objects.values(
                "wake_version",
                "wake_sent_version",
                "wake_next_attempt_at",
                "claim_token",
                "attempt_count",
            ).first()
            RookRequestBudget.objects.values("scope", "revision", "requests_today").first()
            duplicates = RookOutbox.objects.filter(
                job_type=HealthJobType.FETCH_ROOK_DATA,
                status=HealthJobStatus.RUNNING,
                connection_id__isnull=False,
            ).values("connection_id").annotate(count=Count("pk")).filter(count__gt=1).exists()
            if duplicates:
                errors.append(
                    "Duplicate RUNNING fetch jobs exist; owner review is required "
                    "before adding the unique constraint."
                )
        except DatabaseError:
            errors.append(
                "Database or required ROOK schema is unavailable. "
                "Review/apply owner-generated migrations."
            )
        # No WEARABLES_ENABLED kill switch; gate is WEARABLES_REQUIRE_PROFILE_FEATURE + PostHog.
        self.stdout.write(json.dumps({
            "event": "rook_release_preflight",
            "outcome": "failed" if errors else "passed",
            "errors": errors,
            "limitations": [
                "Does not validate the physical unique index; review migrations.",
                "No ROOK API, AWS IAM/network, integration or load tests are executed.",
            ],
        }))
        if errors:
            raise CommandError("ROOK preflight failed; no changes were made.")
