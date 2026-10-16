"""Scheduled aggregate-only operations alert transport for V1.

Use `health_phase1_status` to compute status; never transmit member records,
provider tokens or webhook payloads to an operations destination.
"""
import io
import json
import os
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Deliver non-PHI ROOK/health operational alerts to a configured HTTPS webhook."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        output = io.StringIO()
        call_command("health_phase1_status", hours=options["hours"], stdout=output)
        payload = json.loads(output.getvalue().strip().splitlines()[-1])
        alerts = payload.get("alerts") or []
        if not alerts:
            self.stdout.write("Phase 1 operational status healthy; no alert sent.")
            return
        message = {"text": "Biopeak Phase 1 requires attention: " + ", ".join(alerts),
                   "alerts": alerts, "windowHours": options["hours"],
                   "generatedAt": payload["generatedAt"]}
        if options["dry_run"]:
            self.stdout.write(json.dumps(message))
            return
        endpoint = (getattr(settings, "HEALTH_OPS_ALERT_WEBHOOK_URL", "")
                    or os.environ.get("HEALTH_OPS_ALERT_WEBHOOK_URL", "")).strip()
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise CommandError("HEALTH_OPS_ALERT_WEBHOOK_URL must be a configured HTTPS webhook.")
        try:
            response = requests.post(endpoint, json=message, timeout=(5, 10))
            response.raise_for_status()
        except requests.RequestException as error:
            raise CommandError("Phase 1 alert delivery failed; check operations endpoint.") from error
        self.stdout.write(self.style.SUCCESS("Phase 1 operational alert delivered."))
