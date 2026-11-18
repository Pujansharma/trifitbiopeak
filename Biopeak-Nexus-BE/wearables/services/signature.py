import hashlib
import hmac

from django.conf import settings


def _walk_metadata_datetime(node) -> str:
    """Recursively locate the unmodified ROOK metadata timestamp."""
    if isinstance(node, dict):
        metadata = node.get("metadata")
        if isinstance(metadata, dict):
            value = metadata.get("datetime_string")
            if isinstance(value, str) and value:
                return value
        for value in node.values():
            found = _walk_metadata_datetime(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_metadata_datetime(item)
            if found:
                return found
    return ""


def rook_metadata_datetime_string(payload: dict) -> str:
    """Read the original nested ROOK timestamp, not a reformatted instant."""
    return _walk_metadata_datetime(payload)


def signature_message(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    client_uuid = payload.get("client_uuid")
    rook_user_id = payload.get("user_id")
    # ROOK's published contract uses `metadata.datetime_string` for data;
    # status notifications can instead provide `action_datetime`.
    # Data documents use nested metadata.datetime_string. Signed notification
    # v2 uses action_datetime; the ROOK portal's notification test may send
    # metadata.datetime instead. Keep the exact unmodified string.
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    datetime_value = (
        rook_metadata_datetime_string(payload)
        or payload.get("action_datetime")
        or metadata.get("datetime")
        or payload.get("datetime")
    )
    if not all(isinstance(value, str) and value for value in
               (client_uuid, rook_user_id, datetime_value)):
        return ""
    return f"{client_uuid}{rook_user_id}{datetime_value}"


def verify_rook_webhook_signature(*, payload, signature_header: str) -> bool:
    hash_key = getattr(settings, "ROOK_WEBHOOK_HASH_KEY", "")
    # Fail closed even in development. A public webhook may not accept unsigned
    # medical data, regardless of the retired ALLOW_UNSIGNED configuration.
    if not hash_key:
        return False
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
