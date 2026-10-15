"""Read-only preflight for the Biopeak ROOK data pipeline."""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection

from wearables.models import (
    HealthObservation,
    HealthProcessingJob,
    RookHealthDocument,
    RookMemberIdentity,
    WearableConnection,
)
from wearables.utils.constants import HealthJobStatus


class Command(BaseCommand):
    help = "Read-only checks for ROOK tables, configuration, and queued health data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--require-provider",
            action="store_true",
            help="Also fail when ROOK server credentials or webhook signature key are unset.",
        )

    def handle(self, *args, **options):
        failures = []
        require_provider = options["require_provider"]

        enabled = bool(getattr(settings, "WEARABLES_ENABLED", False))
        timeline_enabled = bool(getattr(settings, "TIMELINE_ENABLED", False))
        signed_webhooks = bool(getattr(settings, "ROOK_WEBHOOK_HASH_KEY", ""))
        unsigned_allowed = bool(
            getattr(settings, "ROOK_ALLOW_UNSIGNED_WEBHOOKS", False)
        )
        server_configured = all(
            (
                getattr(settings, "ROOK_CLIENT_UUID", ""),
                getattr(settings, "ROOK_SECRET_KEY", ""),
                getattr(settings, "ROOK_BASE_URL", ""),
            )
        )
        self.stdout.write(f"Settings: {settings.SETTINGS_MODULE}")
        self.stdout.write(f"Wearables enabled: {enabled}")
        self.stdout.write(f"Timeline enabled: {timeline_enabled}")
        self.stdout.write(f"ROOK environment: {getattr(settings, 'ROOK_ENVIRONMENT', 'unset')}")
        self.stdout.write(f"ROOK server credentials present: {server_configured}")
        self.stdout.write(f"ROOK webhook signature key present: {signed_webhooks}")
        self.stdout.write(f"Unsigned ROOK webhooks enabled: {unsigned_allowed}")

        if not enabled:
            failures.append("Enable wearables for staging with STG_WEARABLES_ENABLED=True.")
        if not timeline_enabled:
            self.stdout.write(self.style.WARNING("Timeline is disabled (optional for ingestion)."))
        if unsigned_allowed:
            failures.append("Disable unsigned ROOK webhooks before using a public URL.")
        if require_provider and not server_configured:
            failures.append("Set STG_ROOK_CLIENT_UUID and STG_ROOK_SECRET_KEY.")
        if require_provider and not signed_webhooks:
            failures.append("Set STG_ROOK_WEBHOOK_HASH_KEY in staging and ROOK Portal.")

        try:
            existing_tables = set(connection.introspection.table_names())
        except DatabaseError as error:
            raise CommandError(
                "Database connection failed; confirm the STG_DB_* variables, "
                "Aiven network permissions and STG_DB_SSLMODE=require."
            ) from error

        wearable_models = list(apps.get_app_config("wearables").get_models())
        missing_models = [
            model.__name__
            for model in wearable_models
            if model._meta.db_table not in existing_tables
        ]
        if missing_models:
            failures.append(
                "Missing wearables DB tables for: " + ", ".join(missing_models)
                + ". Generate/review wearables migrations and run migrate."
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"All {len(wearable_models)} ROOK model tables are present."
                )
            )
            self.stdout.write(
                f"ROOK identities: {RookMemberIdentity.objects.count()} | "
                f"connections: {WearableConnection.objects.count()} | "
                f"documents: {RookHealthDocument.objects.count()} | "
                f"observations: {HealthObservation.objects.count()} | "
                f"queued/retrying jobs: {HealthProcessingJob.objects.filter(status__in=[HealthJobStatus.PENDING, HealthJobStatus.FAILED]).count()}"
            )

        if failures:
            for failure in failures:
                self.stderr.write(self.style.ERROR(failure))
            raise CommandError(f"ROOK preflight failed ({len(failures)} issue(s)).")
        self.stdout.write(self.style.SUCCESS("ROOK preflight passed; external data flow is not yet proven."))
