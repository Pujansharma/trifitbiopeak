"""Rebuild derived health summaries after an approved algorithm-version change.

EC-093: observations remain append-only, only recomputable daily summaries,
trend snapshots and worker-local presentation caches are affected.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.customers.models import CustomerProfile
from wearables.models import HealthDomainSnapshot, HealthObservation
from wearables.services.analytics import refresh_profile_snapshots
from wearables.services.ingestion import rebuild_daily_summaries
from wearables.utils.constants import ALGORITHM_VERSION


class Command(BaseCommand):
    help = "Recompute V1 derived wearable summaries for changed algorithm versions."

    def add_arguments(self, parser):
        parser.add_argument("--customer-profile-id", default="")
        parser.add_argument("--force", action="store_true")
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if options["limit"] < 1 or options["limit"] > 10000:
            raise ValueError("limit must be between 1 and 10000")
        queryset = CustomerProfile.objects.filter(
            health_observations__is_current=True,
        ).distinct().order_by("pk")
        if options["customer_profile_id"]:
            queryset = queryset.filter(pk=options["customer_profile_id"])
        visited, regenerated = 0, 0
        for profile in queryset[:options["limit"]].iterator():
            visited += 1
            current_version = not HealthDomainSnapshot.objects.filter(
                customer_profile=profile,
            ).exclude(algorithm_version=ALGORITHM_VERSION).exists()
            has_snapshots = HealthDomainSnapshot.objects.filter(customer_profile=profile).exists()
            if not options["force"] and current_version and has_snapshots:
                continue
            regenerated += 1
            if options["dry_run"]:
                continue
            with transaction.atomic():
                affected = HealthObservation.objects.filter(
                    customer_profile=profile, is_current=True,
                ).values_list("local_date", "domain").distinct()
                by_day = {}
                for local_day, domain in affected.iterator():
                    by_day.setdefault(local_day, set()).add(domain)
                for local_day, domains in by_day.items():
                    rebuild_daily_summaries(
                        customer_profile=profile, local_date=local_day,
                        domains=domains,
                    )
                refresh_profile_snapshots(profile)
        self.stdout.write(self.style.SUCCESS(
            f"Profiles scanned: {visited}; requiring recomputation: {regenerated}; "
            f"dry run: {options['dry_run']}; algorithm: {ALGORITHM_VERSION}"
        ))
