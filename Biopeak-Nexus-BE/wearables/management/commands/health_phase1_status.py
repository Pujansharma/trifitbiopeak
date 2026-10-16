"""Read-only Phase 1 operations/alert report for cron and support teams."""
import json
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Q
from django.utils import timezone

from wearables.models import (
    HealthProcessingJob, RookHealthDocument, RookWebhookReceipt, WearableConnection,
    WearableConnectionEvent,
)
from wearables.utils.constants import ConnectionStatus, DocumentStatus, HealthJobStatus


class Command(BaseCommand):
    help = "Phase 1: emit privacy-safe sync, import and webhook operational metrics."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--strict", action="store_true", help="Exit nonzero if any operational alert fires")

    def handle(self, *args, **options):
        hours = options["hours"]
        if hours < 1 or hours > 720:
            raise ValueError("hours must be between 1 and 720")
        now = timezone.now()
        since = now - timedelta(hours=hours)
        webhook = RookWebhookReceipt.objects.filter(received_at__gte=since)
        webhook_counts = dict(webhook.values_list("status").annotate(n=Count("pk")))
        total_receipts = sum(webhook_counts.values())
        rejected = webhook_counts.get(DocumentStatus.REJECTED, 0)
        completed = webhook_counts.get(DocumentStatus.PROCESSED, 0)
        processing_jobs = HealthProcessingJob.objects.filter(created_at__gte=since)
        job_counts = dict(processing_jobs.values_list("status").annotate(n=Count("pk")))
        stalled = WearableConnection.objects.filter(
            import_status="running", import_started_at__lt=now - timedelta(hours=4),
        ).count()
        sync_delayed = WearableConnection.objects.filter(
            status__in=[ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL],
        ).filter(
            Q(last_successful_sync__isnull=True)
            | Q(last_successful_sync__lt=now - timedelta(hours=getattr(settings, "ROOK_SYNC_DELAY_HOURS", 48)))
        ).count()
        overdue_documents = RookHealthDocument.objects.filter(
            status=DocumentStatus.QUEUED, received_at__lt=now - timedelta(minutes=15),
        ).count()
        schema_events = WearableConnectionEvent.objects.filter(
            event_type="unmapped_or_empty_rook_document", created_at__gte=since,
        ).count()
        closed_upstream_accounts = WearableConnection.objects.filter(
            last_error_code="provider_account_closed",
        ).count()
        alerts = []
        if stalled:
            alerts.append("historical_import_stalled")
        if sync_delayed:
            alerts.append("sync_delayed")
        if total_receipts >= 20 and rejected / total_receipts > 0.005:
            alerts.append("webhook_rejection_rate_above_0.5_percent")
        if job_counts.get(HealthJobStatus.FAILED, 0) > 0:
            alerts.append("health_processing_jobs_failed")
        if overdue_documents:
            alerts.append("queued_documents_not_normalized")
        if schema_events >= 3:
            alerts.append("rook_schema_or_empty_document_drift")
        if closed_upstream_accounts:
            alerts.append("rook_provider_accounts_closed")
        # Database snapshots are the deliberate supported fallback when Redis
        # is absent; flag reduced performance as a warning, not a broken alert.
        warnings = []
        if not getattr(settings, "HEALTH_REDIS_URL", ""):
            warnings.append("shared_health_redis_not_configured_db_snapshot_fallback")
        payload = {
            "generatedAt": now.isoformat(), "windowHours": hours,
            "webhookReceipts": total_receipts,
            "webhookProcessed": completed,
            "webhookRejected": rejected,
            "webhookRejectedRate": round(rejected / total_receipts, 4) if total_receipts else None,
            "jobCounts": job_counts,
            "importsStalledOverFourHours": stalled,
            "delayedConnections": sync_delayed,
            "unprocessedQueuedDocuments": overdue_documents,
            "unmappedRookDocuments": schema_events,
            "closedProviderAccounts": closed_upstream_accounts,
            "alerts": alerts,
            "warnings": warnings,
        }
        self.stdout.write(json.dumps(payload, sort_keys=True))
        if alerts and options["strict"]:
            self.stderr.write("Biopeak Phase 1 operational health check failed.")
            raise SystemExit(2)
