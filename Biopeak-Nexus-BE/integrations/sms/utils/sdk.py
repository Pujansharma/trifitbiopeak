import threading

import requests
from django.conf import settings

from core.utils.log import logger

SMS_BASE_URL = "https://control.msg91.com/api/v5/flow"


class Session(requests.Session):
    def __init__(self, api_key: str):
        super().__init__()
        self.headers.update({
            "User-Agent": "Biopeak-Nexus-Admin-V1",
            "Content-Type": "application/json",
            "authkey": api_key
        })


class SMSMessage:
    def __init__(
            self,
            template_id: str,
            recipients: list
    ):
        self.api_key: str | None = getattr(settings, "SMS_API_KEY", None)
        self.payload = {
            "template_id": template_id,
            "recipients": recipients,
        }

    def send(self):
        """Send the message synchronously through MSG91."""
        api_key = self.api_key
        if not api_key:
            logger.warning("[SMS]: Sending skipped because SMS_API_KEY is not configured.")
            return None
        with Session(api_key) as session:
            response = session.post(SMS_BASE_URL, json=self.payload)
            if not response.ok:
                logger.warning(f"[SMS]: SENDING FAILED, Response= {response.text}")
                logger.warning(f"[SMS]: Response code= {response.status_code}")
                return None
            return response.json()


class SMSThread(threading.Thread):
    def __init__(self, message: SMSMessage):
        super().__init__()
        self.message = message

    def run(self):
        self.message.send()


def send_sms_message(template_id: str, recipients: list):
    """Start a background thread to send the message without rate limiting."""
    message = SMSMessage(template_id, recipients)
    SMSThread(message).start()
