"""Optional privacy operation; policy approval required before execution."""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from wearables.models import RookHealthDocument
from wearables.utils.constants import DocumentStatus


class Command(BaseCommand):
    help = "Review or purge raw ROOK payloads after approved retention; canonical history stays."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-days", type=int, required=True,
            help="Approved minimum retention period for processed raw payloads.",
        )
        parser.add_argument(
            "--execute", action="store_true",
            help="Actually empty eligible processed raw payloads (dry-run by default).",
        )

    def handle(self, *args, **options):
        days = options["older_than_days"]
        if days < 1:
            raise CommandError("--older-than-days must be a positive integer.")
        cutoff = timezone.now() - timedelta(days=days)
        eligible = RookHealthDocument.objects.filter(
            status=DocumentStatus.PROCESSED,
            processed_at__lte=cutoff,
        ).exclude(payload={})
        count = eligible.count()
        if not options["execute"]:
            self.stdout.write(f"DRY RUN: {count} processed raw payload(s) eligible after {days} days.")
            return
        updated = eligible.update(payload={}, updated_at=timezone.now())
        self.stdout.write(self.style.SUCCESS(
            f"Purged raw payload from {updated} processed documents; canonical observations retained."
        ))
