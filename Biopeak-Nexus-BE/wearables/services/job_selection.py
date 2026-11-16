"""Bounded database selectors and reconciliation for the ROOK job queue."""
from datetime import timedelta

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from wearables.models import RookOutbox, RookHealthDocument, WearableConnection
from wearables.services.ingestion import normalize_health_document
from wearables.services.job_queue import finished_health_jobs
from wearables.services.job_claims import rook_outbox_retryable_q
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionMethod, ConnectionStatus, DocumentStatus,
    HealthJobStatus, HealthJobType, HistoricalImportStatus,
)


def connections_requiring_fetch_rook_data():
    now = timezone.now()
    delayed_before = now - timedelta(
        hours=getattr(settings, "ROOK_SYNC_DELAY_HOURS", 48)
    )
    related_jobs = RookOutbox.objects.filter(
        connection_id=OuterRef("pk"), job_type=HealthJobType.FETCH_ROOK_DATA,
    )
    open_jobs = related_jobs.filter(
        Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
        | Q(status=HealthJobStatus.FAILED) & rook_outbox_retryable_q()
    )
    recent_jobs = finished_health_jobs(related_jobs).filter(
        completed_at__gt=now - timedelta(hours=1),
    )
    return (
        WearableConnection.objects.select_related("customer_profile")
        .filter(
            status__in=[
                ConnectionStatus.ACTIVE,
                ConnectionStatus.IDLE,
                ConnectionStatus.PARTIAL,
                ConnectionStatus.PROVIDER_ERROR,
                ConnectionStatus.IMPORTING,
                ConnectionStatus.HISTORICAL_REIMPORT,
            ],
            connection_method=ConnectionMethod.API,
            authorization_status=AuthorizationStatus.AUTHORIZED,
        )
        .filter(
            Q(last_successful_sync__isnull=True)
            | Q(last_successful_sync__lt=delayed_before)
            | (Q(import_status__in=[HistoricalImportStatus.RUNNING, HistoricalImportStatus.PARTIAL])
               & (Q(import_started_at__isnull=True)
                  | Q(import_started_at__lt=now - timedelta(hours=4))))
        )
        .annotate(has_open_recovery=Exists(open_jobs), recently_attempted=Exists(recent_jobs))
        .filter(has_open_recovery=False, recently_attempted=False)
    )


def enqueue_orphaned_normalization_jobs(*, grace_minutes: int = 10, limit: int = 100) -> dict:
    """Finish orphan QUEUED documents inline."""
    cutoff = timezone.now() - timedelta(minutes=max(1, grace_minutes))
    unprocessed = RookHealthDocument.objects.filter(
        status=DocumentStatus.QUEUED, received_at__lt=cutoff,
    ).exclude(payload={}).order_by("received_at", "pk")[:max(0, min(limit, 100))]
    processed_count = 0
    failed_count = 0
    for document in unprocessed.iterator():
        outcome = normalize_health_document(document.pk, enqueue_analytics=True)
        if outcome.get("skipped") and outcome.get("reason") not in {
            "already_processing_or_not_queued",
            "consent_revoked",
        }:
            failed_count += 1
            continue
        if outcome.get("skipped") and outcome.get("reason") == "consent_revoked":
            continue
        processed_count += 1
    return {"queued": processed_count, "requiresOperatorReview": failed_count}
