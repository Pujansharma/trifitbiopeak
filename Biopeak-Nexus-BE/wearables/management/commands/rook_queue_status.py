"""Operational status uses database jobs, never SQS depth as a completion proxy."""
import json

from django.core.management.base import BaseCommand
from django.db.models import Count, Min
from django.utils import timezone

from wearables.models import RookOutbox
from wearables.services.job_claims import rook_outbox_exhausted_q, rook_outbox_retryable_q
from wearables.utils.constants import HealthJobStatus, HealthJobType


class Command(BaseCommand):
    help = "Report ROOK queue health without member health data or credentials."

    def handle(self, *args, **options):
        now = timezone.localtime()
        states = list(RookOutbox.objects.values("job_type", "status").annotate(count=Count("pk")))
        ready = RookOutbox.objects.filter(
            status__in=(HealthJobStatus.PENDING, HealthJobStatus.FAILED),
            scheduled_at__lte=now,
        ).filter(rook_outbox_retryable_q())
        oldest = ready.aggregate(oldest=Min("scheduled_at"))["oldest"]
        running_fetch = RookOutbox.objects.filter(
            job_type=HealthJobType.FETCH_ROOK_DATA,
            status=HealthJobStatus.RUNNING,
        ).count()
        self.stdout.write(json.dumps({
            "event": "rook_queue_status",
            "states": states,
            "ready": ready.count(),
            "oldestReadyAgeSeconds": max(0, (now - oldest).total_seconds()) if oldest else 0,
            "exhausted": RookOutbox.objects.filter(
                status=HealthJobStatus.FAILED,
            ).filter(rook_outbox_exhausted_q()).count(),
            "runningFetchJobs": running_fetch,
        }, default=str))
