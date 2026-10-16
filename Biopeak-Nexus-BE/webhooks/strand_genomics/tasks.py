"""Store provider callbacks and dispatch webhook workers."""

import threading

from django.db import close_old_connections

from integrations.strand_genomics.utils.webhooks import handle_strand_genomics_webhook
from webhooks.strand_genomics.models import StrandGenomicsWebhook


def process_strand_genomics_webhook(payload: dict):
    close_old_connections()
    try:
        StrandGenomicsWebhook.objects.create(data=payload)
        return handle_strand_genomics_webhook(payload)
    finally:
        close_old_connections()


class StrandGenomicsWebhookThread(threading.Thread):
    def __init__(self, payload: dict):
        super().__init__()
        self.payload = payload

    def run(self):
        process_strand_genomics_webhook(self.payload)


def start_strand_genomics_webhook_task(payload: dict):
    StrandGenomicsWebhookThread(payload).start()
