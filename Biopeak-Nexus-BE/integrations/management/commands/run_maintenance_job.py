from django.core.management.base import BaseCommand

from appointments.appointment_integrity.scans import process_pending_exception_scans
from integrations.communications.service import enqueue_due_appointment_reminders
from integrations.communications.whatsapp.outbox import dispatch_eligible_whatsapp_jobs
from integrations.google_calendar.outbox import dispatch_eligible_google_calendar_jobs
from integrations.google_calendar.webhook_channel import (
    renew_expiring_google_calendar_watch_channels,
)
from integrations.protocol_management.outbox import dispatch_eligible_protocol_ai_jobs
from integrations.protocol_management.versions import sweep_protocol_versions


class Command(BaseCommand):
    help = (
        "Single 15m Chronos entrypoint: WA reminders/outbox, Google Calendar "
        "outbox/watches, protocol AI outbox, protocol versions, exception scans."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Max rows to enqueue/dispatch/drain per subsystem this run.",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        lines = []

        reminders = enqueue_due_appointment_reminders(limit=limit)
        wa_batches = dispatch_eligible_whatsapp_jobs(limit=limit)
        lines.append(
            f"WA: enqueued {len(reminders)} reminder(s); "
            f"published {wa_batches} SQS batch(es)."
        )

        gc_batches = dispatch_eligible_google_calendar_jobs(limit=limit)
        renewed, renew_failed = renew_expiring_google_calendar_watch_channels()
        lines.append(
            f"Google: published {gc_batches} SQS batch(es); "
            f"renewed {renewed} watch(es); {renew_failed} renew fail(s)."
        )

        ai_batches = dispatch_eligible_protocol_ai_jobs(limit=limit)
        lines.append(f"Protocol AI: published {ai_batches} SQS batch(es).")

        expired_count, activated_count = sweep_protocol_versions()
        lines.append(
            f"Protocol versions: expired {expired_count}; "
            f"activated {activated_count}."
        )

        scan_processed = process_pending_exception_scans(limit=limit)
        lines.append(
            f"Exception scans: processed {scan_processed} pending job(s)."
        )

        for line in lines:
            self.stdout.write(self.style.SUCCESS(line))
