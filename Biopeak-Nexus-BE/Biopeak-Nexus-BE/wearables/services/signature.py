import hashlib
import hmac

from django.conf import settings


def metadata_datetime_string(node) -> str:
    """Locate the signed metadata timestamp in a ROOK health document.

    The ROOK portal signs the literal ``metadata.datetime_string``; this
    timestamp is often nested under sleep/physical/body summary objects.
    """
    if isinstance(node, dict):
        metadata = node.get("metadata")
        if isinstance(metadata, dict):
            timestamp = metadata.get("datetime_string")
            if isinstance(timestamp, str) and timestamp:
                return timestamp
        for value in node.values():
            timestamp = metadata_datetime_string(value)
            if timestamp:
                return timestamp
    elif isinstance(node, list):
        for item in node:
            timestamp = metadata_datetime_string(item)
            if timestamp:
                return timestamp
    return ""


def signature_message(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    client_uuid = payload.get("client_uuid")
    user_id = payload.get("user_id")
    # Retain the legacy root datetime fallback for existing notification
    # payloads; actual health documents use metadata.datetime_string.
    timestamp = metadata_datetime_string(payload) or payload.get("datetime")
    if not all(isinstance(value, str) and value for value in (client_uuid, user_id, timestamp)):
        return ""
    return f"{client_uuid}{user_id}{timestamp}"


def verify_rook_webhook_signature(
    *,
    payload,
    signature_header: str,
) -> bool:
    hash_key = getattr(settings, "ROOK_WEBHOOK_HASH_KEY", "")
    allow_unsigned = getattr(settings, "ROOK_ALLOW_UNSIGNED_WEBHOOKS", False)
    if not hash_key:
        return allow_unsigned
    if not isinstance(payload, dict) or not signature_header:
        return False
    message = signature_message(payload)
    if not message:
        return False
    expected_signature = hmac.new(
        key=hash_key.encode("utf-8"),
        msg=message.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_signature, signature_header)

