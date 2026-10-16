from io import BytesIO
from urllib.parse import quote

import requests
from django.conf import settings

from core.utils.formatters import PhoneNumberFormat
from core.utils.log import logger

ORANGE_LABS_API_BASE_URL = getattr(settings, "ORANGE_LABS_API_BASE_URL", None)
ORANGE_LABS_API_KEY = getattr(settings, "ORANGE_LABS_API_KEY", None)


class OrangeLabsSession(requests.Session):
    def __init__(self, api_key=ORANGE_LABS_API_KEY):
        super().__init__()
        self.headers.update(
            {
                "api_key": api_key or "",
                "Content-Type": "application/json",
            }
        )


def _require_base_url():
    if not ORANGE_LABS_API_BASE_URL:
        raise ValueError("ORANGE_LABS_API_BASE_URL is not configured")
    return ORANGE_LABS_API_BASE_URL.rstrip("/")


def check_serviceability(address, request_date):
    base_url = _require_base_url()
    url = f"{base_url}/v1/partner/serviceability?address={quote(address)}&request_date={request_date}"
    session = OrangeLabsSession()
    response = session.get(url)
    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text}
    if not response.ok and response.status_code != 400:
        logger.warning(
            f"Orange Labs serviceability error {response.status_code}: {payload}"
        )
    return response.status_code, payload


def create_order(payload):
    base_url = _require_base_url()
    url = f"{base_url}/v1/partner/order"
    session = OrangeLabsSession()
    response = session.post(url, json=payload)
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if not response.ok:
        logger.warning(f"Orange Labs create order error {response.status_code}: {body}")
    return response.status_code, body


def reschedule_order(request_id, token, requested_slot_time, reason, explanation):
    base_url = _require_base_url()
    url = f"{base_url}/v1/partner/{request_id}/reschedule"
    session = OrangeLabsSession()
    response = session.patch(
        url,
        params={"token": token},
        json={
            "requested_slot_time": requested_slot_time,
            "reschedule_reason": reason,
            "reschedule_explanation": explanation,
        },
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if not response.ok:
        logger.warning(f"Orange Labs reschedule error {response.status_code}: {body}")
    return response.status_code, body


def cancel_order(request_id, token, reason, explanation):
    base_url = _require_base_url()
    url = f"{base_url}/v1/partner/{request_id}/cancel"
    session = OrangeLabsSession()
    response = session.patch(
        url,
        params={"token": token},
        json={
            "cancellationReason": reason,
            "cancellationExplanation": explanation,
        },
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if not response.ok:
        logger.warning(f"Orange Labs cancel error {response.status_code}: {body}")
    return response.status_code, body


def fetch_order(api_key: str, phone: str):
    base_url = _require_base_url()
    url = f"{base_url}/test-results"
    session = OrangeLabsSession(api_key)
    formatter = PhoneNumberFormat(phone)
    national_number = formatter.get_national_number()
    if not national_number:
        error_message = "Invalid phone number provided"
        logger.error(error_message)
        return None, error_message

    logger.info("OrangeHealth report request started")
    response = session.get(
        url,
        params={"primary_patient_number": national_number},
    )
    if not response.ok:
        error_message = "Unable to retrieve OrangeHealth reports"
        logger.error(
            f"OrangeHealth report request failed: status={response.status_code}"
        )
        return None, error_message

    payload = response.json()
    logger.info("OrangeHealth report request completed")
    return payload, None


def get_pdf_report(report_url: str):
    """Download one OrangeHealth PDF report."""
    logger.info("OrangeHealth PDF download started")
    response = requests.get(report_url)
    if not response.ok:
        error_message = "Unable to download the OrangeHealth report"
        logger.error(
            f"OrangeHealth PDF download failed: status={response.status_code}"
        )
        return None, error_message

    if not response.content:
        error_message = "OrangeHealth returned an empty PDF report"
        logger.warning(error_message)
        return None, error_message

    logger.info("OrangeHealth PDF download completed")
    return BytesIO(response.content), None
