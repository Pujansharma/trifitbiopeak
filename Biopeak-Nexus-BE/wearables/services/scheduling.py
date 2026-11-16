"""Midnight discovery enqueues fetch jobs; this module does not download data.

Stale mode only: pull coverage at least seven days old.
Timezone is Django TIME_ZONE (Asia/Kolkata). AWS schedule must match.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from wearables.models import RookOutbox, WearableConnection, WearableConsent
from wearables.services.job_claims import rook_outbox_retryable_q
from wearables.services.job_queue import enqueue_or_reuse_fetch_rook_data_job
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionMethod, ConnectionStatus, ConsentStatus,
    HealthJobStatus, HealthJobType,
)

NIGHTLY_PAGE_SIZE = 100
MAX_OPEN_SCHEDULED_SYNCS = 100
NIGHTLY_SYNC_MODE = "stale"
NIGHTLY_STALE_DAYS = 7


def nightly_timezone() -> ZoneInfo:
    return ZoneInfo(str(settings.TIME_ZONE))


def eligible_nightly_connections(payload: dict):
    consent = WearableConsent.objects.filter(
        customer_profile_id=OuterRef("customer_profile_id"),
        status=ConsentStatus.GRANTED, revoked_at__isnull=True,
    )
    query = WearableConnection.objects.select_related("customer_profile", "identity").filter(
        Exists(consent), connection_method=ConnectionMethod.API,
        authorization_status=AuthorizationStatus.AUTHORIZED, disconnected_at__isnull=True,
    ).exclude(status__in=(ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED)).exclude(
        last_error_code="provider_account_closed",
    )
    if payload["mode"] == "stale":
        cutoff = datetime.fromisoformat(payload["cutoff"])
        query = query.filter(Q(synced_through__isnull=True) | Q(synced_through__lte=cutoff))
    if payload.get("cursor"):
        query = query.filter(pk__gt=payload["cursor"])
    return query.order_by("pk")


def run_rook_sync_scan(*, now=None) -> dict:
    """Enqueue fetch_rook_data for stale connections. Idempotent per local date."""
    now = now or timezone.now()
    mode = NIGHTLY_SYNC_MODE
    run_date = now.astimezone(nightly_timezone()).date().isoformat()
    payload = {
        "runDate": run_date,
        "mode": mode,
        "cursor": None,
        "cutoff": (now - timedelta(days=NIGHTLY_STALE_DAYS)).isoformat(),
    }
    enqueued_count = 0
    while True:
        open_count = RookOutbox.objects.filter(job_type=HealthJobType.FETCH_ROOK_DATA).filter(
            Q(status__in=(HealthJobStatus.PENDING, HealthJobStatus.RUNNING))
            | Q(status=HealthJobStatus.FAILED) & rook_outbox_retryable_q()
        ).count()
        capacity = max(0, min(NIGHTLY_PAGE_SIZE, MAX_OPEN_SCHEDULED_SYNCS - open_count))
        if not capacity:
            return {
                "deferred": True,
                "reason": "sync_queue_at_capacity",
                "runDate": run_date,
                "enqueuedCount": enqueued_count,
            }
        page = list(eligible_nightly_connections(payload)[:capacity])
        if not page:
            break
        for connection in page:
            _, created = enqueue_or_reuse_fetch_rook_data_job(
                connection=connection,
                customer_profile=connection.customer_profile,
                flow="nightly",
                scheduled_key=f"nightly:{run_date}:{mode}:{connection.pk}",
            )
            payload["cursor"] = str(connection.pk)
            enqueued_count += int(created)
        if len(page) < capacity:
            break
    return {
        "rookSyncScanComplete": True,
        "runDate": run_date,
        "enqueuedCount": enqueued_count,
    }
