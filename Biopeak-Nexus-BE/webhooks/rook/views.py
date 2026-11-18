"""Signed inbound ROOK webhook delivery (not a customer-facing API).

ROOK must be given the public HTTPS URLs under /webhooks/rook/ in its portal.
Requests are signed with X-ROOK-HASH, not a Biopeak user JWT. Data deliveries
are normalized transactionally using the existing RookWebhookReceipt and
HealthDailySummary tables, and are acknowledged only after storage succeeds.
"""

import json
import logging

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.db import DatabaseError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from wearables.services.client import RookServiceError
from wearables.services.ingestion import ingest_rook_document
from wearables.services.signature import verify_rook_webhook_signature

logger = logging.getLogger(__name__)

# ROOK documents a 16 MB maximum for webhook JSON documents.
MAX_ROOK_WEBHOOK_BYTES = 16 * 1024 * 1024


def _respond(message, status):
    return JsonResponse({"detail": message}, status=status)


def _handle_rook_delivery(request):
    """Reject untrusted requests before touching any wearable user data."""
    if request.content_type != "application/json":
        return _respond("Content-Type must be application/json.", 415)
    length_header = request.META.get("CONTENT_LENGTH")
    if length_header:
        try:
            if int(length_header) > MAX_ROOK_WEBHOOK_BYTES:
                return _respond("ROOK document exceeds 16 MB.", 413)
        except ValueError:
            return _respond("Invalid Content-Length.", 400)
    try:
        body = request.body
    except RequestDataTooBig:
        return _respond("ROOK document exceeds the configured request size.", 413)
    if len(body) > MAX_ROOK_WEBHOOK_BYTES:
        return _respond("ROOK document exceeds 16 MB.", 413)
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return _respond("Request body must contain valid JSON.", 400)
    if not isinstance(payload, dict):
        return _respond("ROOK payload must be a JSON object.", 400)

    client_uuid = str(getattr(settings, "ROOK_CLIENT_UUID", "") or "").strip()
    signing_key = str(getattr(settings, "ROOK_WEBHOOK_HASH_KEY", "") or "").strip()
    if not client_uuid or not signing_key:
        # Do not acknowledge deliveries while signing configuration is missing.
        # ROOK retries non-2xx responses; never accept unsigned health data.
        logger.error("ROOK inbound webhook is not configured: missing client UUID or signing key")
        return _respond("ROOK webhook verification is not configured.", 503)
    if payload.get("client_uuid") != client_uuid:
        return _respond("Invalid ROOK webhook client.", 403)
    if not verify_rook_webhook_signature(
        payload=payload,
        signature_header=request.headers.get("X-ROOK-HASH", ""),
    ):
        return _respond("Invalid ROOK webhook signature.", 403)
    try:
        result = ingest_rook_document(payload, signature_valid=True)
    except (TypeError, ValueError):
        # Malformed data must not be silently acknowledged as successfully saved.
        logger.warning("ROOK data webhook payload could not be processed")
        return _respond("Invalid ROOK webhook payload.", 422)
    except RookServiceError:
        logger.warning("ROOK data webhook processing was deferred")
        return _respond("ROOK webhook processing could not complete. Retry delivery.", 503)
    except DatabaseError:
        logger.exception("ROOK webhook database operation failed")
        return _respond("ROOK webhook storage unavailable. Retry delivery.", 503)
    except Exception:
        # Returning 200 here would lose the delivery. Avoid exposing patient data
        # or internal exception strings to the external caller.
        logger.exception("Unexpected ROOK webhook processing failure")
        return _respond("ROOK webhook processing could not complete. Retry delivery.", 503)

    # The existing processor already handles duplicates and unknown users.
    # No raw health payloads are reflected in the response.
    response = {"accepted": True}
    for key in ("duplicate", "skipped", "reason", "processed", "queued"):
        if key in result:
            response[key] = result[key]
    return JsonResponse(response, status=200)


@csrf_exempt
@require_POST
def rook_data_webhook(request):
    """ROOK Data Webhook: health events/summaries, normalized into existing tables."""
    return _handle_rook_delivery(request)

