"""Store provider callbacks and dispatch webhook workers."""

import threading

from django.db import close_old_connections

from integrations.bugspeaks.utils.webhooks import handle_bugspeaks_webhook
from webhooks.bugspeaks.models import BugspeaksWebhook


def process_bugspeaks_webhook(payload: dict) -> tuple[bool | None, str | None]:
    close_old_connections()
    try:
        BugspeaksWebhook.objects.create(data=payload)
        return handle_bugspeaks_webhook(payload)
    finally:
        close_old_connections()


class BugspeaksWebhookThread(threading.Thread):
    def __init__(self, payload: dict) -> None:
        super().__init__()
        self.payload = payload

    def run(self) -> None:
        process_bugspeaks_webhook(self.payload)


def start_bugspeaks_webhook_task(payload) -> None:
    BugspeaksWebhookThread(payload).start()
