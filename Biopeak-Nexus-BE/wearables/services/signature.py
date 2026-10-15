import hashlib
import hmac

from django.conf import settings


def rook_metadata_datetime_string(payload: dict) -> str:
    """Read ROOK's literal metadata datetime without normalizing timezone/format.

    Real ROOK v2 health documents nest this under a pillar's summary/events.
    Simple sandbox fixtures use the envelope's `datetime` field instead.
    """
    def walk(node):
        if isinstance(node, dict):
            metadata = node.get("metadata")
            if isinstance(metadata, dict):
                value = metadata.get("datetime_string")
                if isinstance(value, str) and value:
                    return value
            for value in node.values():
                found = walk(value)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = walk(item)
                if found:
                    return found
        return ""

    return walk(payload)


def signature_message(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    client_uuid = payload.get("client_uuid")
    rook_user_id = payload.get("user_id")
    # ROOK's published contract uses `metadata.datetime_string` for data;
    # status notifications can instead provide `action_datetime`.
    datetime_value = (
        rook_metadata_datetime_string(payload)
        or payload.get("action_datetime")
        or payload.get("datetime")
    )
    if not all(isinstance(value, str) and value for value in
               (client_uuid, rook_user_id, datetime_value)):
        return ""
    return f"{client_uuid}{rook_user_id}{datetime_value}"


def verify_rook_webhook_signature(*, payload, signature_header: str) -> bool:
    hash_key = getattr(settings, "ROOK_WEBHOOK_HASH_KEY", "")
    allow_unsigned = getattr(settings, "ROOK_ALLOW_UNSIGNED_WEBHOOKS", False)
    if not hash_key:
        return bool(allow_unsigned)
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
    return hmac.compare_digest(expected_signature, signature_header.strip())
