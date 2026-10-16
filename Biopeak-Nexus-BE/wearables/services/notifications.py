from django.db import transaction
from django.utils.dateparse import parse_datetime
from django.utils import timezone

from wearables.models import RookMemberIdentity, WearableConnection, RookWebhookReceipt, WearableConnectionEvent
from wearables.services.connections import record_connection_event
from wearables.services.job_queue import enqueue_health_job
from wearables.services.lifecycle import valid_transition
from wearables.services.provenance import canonical_source
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    HealthJobType,
    HistoricalImportStatus,
    PermissionStatus,
    DocumentStatus,
)


def notification_text(payload: dict) -> str:
    values = [
        payload.get("action"),
        payload.get("event"),
        payload.get("event_type"),
        payload.get("type"),
        payload.get("status"),
        payload.get("notification_type"),
        payload.get("message"),
    ]
    return (
        " ".join(str(value) for value in values if value)
        .lower()
        .replace("_", " ")
        .replace("-", " ")
    )


def notification_data_source(payload: dict) -> str:
    return canonical_source(
        payload.get("data_source")
        or payload.get("source")
        or payload.get("provider")
        or ""
    )


def notification_action_datetime(payload: dict):
    """Signed ROOK event timestamp, used only when timezone-qualified.

    Missing or ambiguous timestamps cannot safely establish event order.
    """
    value = payload.get("action_datetime")
    if not isinstance(value, str):
        return None
    parsed = parse_datetime(value)
    if parsed is None or timezone.is_naive(parsed):
        return None
    return parsed


def stale_rook_notification(*, connection, action_datetime, text: str) -> bool:
    if action_datetime is None:
        return False
    # A late revoke/expiry from the *old* authorization must not override a
    # confirmed new authorization. We only compare signed, timezone-aware ROOK
    # action times; receipt arrival time cannot establish source event order.
    is_negative = any(word in text for word in (
        "expired", "disconnect", "deauthor", "revoked", "deleted", "closed",
        "denied", "failed", "error", "unauthor", "invalid", "rejected",
    ))
    if (is_negative and connection.authorization_status == AuthorizationStatus.AUTHORIZED
            and connection.import_started_at and action_datetime < connection.import_started_at):
        return True
    prior_notifications = WearableConnectionEvent.objects.filter(
        connection=connection, event_type="rook_notification",
    ).order_by("-created_at")[:20]
    for event in prior_notifications:
        previous = notification_action_datetime({
            "action_datetime": event.payload.get("actionDatetime"),
        })
        if previous is not None and action_datetime < previous:
            return True
    return False


def apply_notification_state(connection: WearableConnection, text: str) -> None:
    # A revoked source cannot be reopened by an out-of-order success message.
    # A new explicit device-connect action must first set authorizing state.
    negative = any(token in text for token in (
        "expired", "disconnect", "deauthor", "revoked", "denied",
        "deleted", "closed", "invalid", "failed", "error",
        "unauthor", "rejected",
    ))
    # A delayed positive provider event cannot restore a locally expired or
    # revoked grant. Only a fresh authenticated connect attempt may do so.
    if connection.status in {ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED} and not negative:
        return
    if any(token in text for token in (
        "account deleted", "account closed", "user deleted", "user closed",
        "provider deleted", "provider account deleted",
    )):
        connection.status = ConnectionStatus.DISCONNECTED
        connection.authorization_status = AuthorizationStatus.REVOKED
        connection.disconnected_at = timezone.now()
        connection.last_error_code = "provider_account_closed"
        connection.last_error_detail = "This upstream account is closed. Connect another provider."
        return
    # "unauthorized" includes the substring "authorized". Check this before
    # matching positive grants so an invalid ROOK token cannot reopen sync.
    if any(token in text for token in (
        "unauthorized", "not authorized", "invalid token", "invalid authorization",
    )):
        connection.status = ConnectionStatus.AUTHORIZATION_EXPIRED
        connection.authorization_status = AuthorizationStatus.EXPIRED
        return
    if any(token in text for token in ("authorization expired", "token expired")):
        connection.status = ConnectionStatus.AUTHORIZATION_EXPIRED
        connection.authorization_status = AuthorizationStatus.EXPIRED
        return
    if any(token in text for token in ("disconnect", "deauthor", "revoked")):
        connection.status = ConnectionStatus.DISCONNECTED
        connection.authorization_status = AuthorizationStatus.REVOKED
        connection.disconnected_at = timezone.now()
        return
    if any(token in text for token in ("permission denied", "insufficient scope")):
        connection.status = ConnectionStatus.PERMISSION_DENIED
        connection.authorization_status = AuthorizationStatus.DENIED
        connection.permission_status = PermissionStatus.DENIED
        return
    if any(token in text for token in ("import started", "historical started")):
        connection.status = ConnectionStatus.IMPORTING
        connection.import_status = HistoricalImportStatus.RUNNING
        connection.import_started_at = timezone.now()
        return
    if any(token in text for token in ("import partial", "historical partial")):
        connection.status = ConnectionStatus.PARTIAL
        connection.import_status = HistoricalImportStatus.PARTIAL
        return
    if any(token in text for token in ("import failed", "historical failed")):
        connection.status = ConnectionStatus.PROVIDER_ERROR
        connection.import_status = HistoricalImportStatus.FAILED
        return
    if any(token in text for token in ("retrieval failed", "fetch failed", "error")):
        connection.status = ConnectionStatus.PROVIDER_ERROR
        return
    if "import completed" in text or "historical completed" in text:
        # ROOK extraction completion is not proof that Biopeak persisted and
        # normalized the documents. A recovery worker must reconcile the local
        # canonical store before making the member-facing import complete.
        if connection.import_status == HistoricalImportStatus.COMPLETED:
            return
        connection.status = ConnectionStatus.IMPORTING
        connection.authorization_status = AuthorizationStatus.AUTHORIZED
        connection.import_status = HistoricalImportStatus.RUNNING
        connection.import_started_at = connection.import_started_at or timezone.now()
        connection.connected_at = connection.connected_at or timezone.now()
        return
    if any(token in text for token in ("connected", "authorized", "authorization completed", "linked")):
        # Generic notifications may be duplicated or delayed. A healthy and
        # already-authorized connection must not re-enter Historical Import.
        if connection.authorization_status == AuthorizationStatus.AUTHORIZED:
            if connection.status in {ConnectionStatus.ACTIVE, ConnectionStatus.IDLE,
                                     ConnectionStatus.PARTIAL, ConnectionStatus.IMPORTING,
                                     ConnectionStatus.HISTORICAL_REIMPORT,
                                     ConnectionStatus.RECONNECTED}:
                return
            if connection.status == ConnectionStatus.PROVIDER_ERROR and connection.import_status == HistoricalImportStatus.COMPLETED:
                connection.status = ConnectionStatus.ACTIVE if connection.last_successful_sync else ConnectionStatus.IDLE
                return
        connection.status = ConnectionStatus.IMPORTING
        connection.authorization_status = AuthorizationStatus.AUTHORIZED
        connection.import_status = HistoricalImportStatus.RUNNING
        connection.import_started_at = connection.import_started_at or timezone.now()
        connection.connected_at = connection.connected_at or timezone.now()


@transaction.atomic
def process_rook_notification(payload: dict, *, signature_valid: bool = False) -> dict:
    rook_user_id = str(payload.get("user_id") or "")
    data_source = notification_data_source(payload)
    if not rook_user_id or not data_source:
        return {"accepted": True, "skipped": True, "reason": "missing_identity"}
    identity = RookMemberIdentity.objects.select_for_update().filter(rook_user_id=rook_user_id).first()
    if identity is None:
        return {"accepted": True, "skipped": True, "reason": "unknown_user"}
    connection = (
        WearableConnection.objects.select_for_update()
        .filter(
            customer_profile=identity.customer_profile,
            data_source=data_source,
        )
        .first()
    )
    if connection is None:
        return {"accepted": True, "skipped": True, "reason": "unknown_connection"}
    # Audit webhook notifications idempotently, independently of ROOK data
    # document receipts. A provider retry must not repeat connection events.
    from wearables.services.ingestion import json_digest, receipt_payload
    receipt, created = RookWebhookReceipt.objects.get_or_create(
        receipt_key=json_digest(["notification", payload]),
        defaults={
            "rook_user_id": rook_user_id,
            "signature_valid": signature_valid,
            "status": DocumentStatus.PROCESSED,
            "reason": "notification",
            "payload": receipt_payload(payload),
            "received_at": timezone.now(),
        },
    )
    if not created:
        return {"accepted": True, "duplicate": True, "connectionId": str(connection.pk)}
    previous_status = connection.status
    text = notification_text(payload)
    event_datetime = notification_action_datetime(payload)
    if stale_rook_notification(
        connection=connection, action_datetime=event_datetime, text=text,
    ):
        receipt.reason = "out_of_order_notification"
        receipt.save(update_fields=["reason", "updated_at"])
        return {"accepted": True, "skipped": True, "reason": "out_of_order_notification"}
    if (connection.last_error_code == "provider_account_closed"
            and not any(token in text for token in ("deleted", "closed"))):
        return {"accepted": True, "skipped": True, "reason": "provider_account_closed"}
    resumed = False
    if (connection.status in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}
            and any(token in text for token in ("authorized", "connected", "linked"))
            and not any(token in text for token in (
                "failed", "denied", "expired", "revoked", "unauthor", "invalid", "rejected",
            ))):
        pending_state = WearableConnectionEvent.objects.filter(
            connection=connection,
            event_type__in=["oauth_state_pending", "oauth_state_verified"],
        ).order_by("-created_at").first()
        if pending_state and pending_state.previous_status in {
            ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED,
        }:
            from wearables.services.connections import authorization_confirmed
            authorization_confirmed(connection, was_reconnect=True)
            resumed = True
    if not resumed:
        apply_notification_state(connection, text)
    if not valid_transition(previous_status, connection.status) and not resumed:
        connection.status = previous_status
        return {"accepted": True, "skipped": True, "reason": "invalid_state_transition"}
    connection.last_webhook_received_at = timezone.now()
    if connection.status == ConnectionStatus.PROVIDER_ERROR:
        connection.last_error_code = "rook_notification"
        connection.last_error_detail = str(payload.get("message") or text)[:512]
    elif connection.last_error_code != "provider_account_closed":
        connection.last_error_code = ""
        connection.last_error_detail = ""
    connection.save()
    from wearables.services.analytics import invalidate_health_dashboard
    invalidate_health_dashboard(connection.customer_profile)
    record_connection_event(
        connection,
        event_type="rook_notification",
        previous_status=previous_status,
        detail=text[:512],
        payload={
            "source": data_source,
            "action": str(payload.get("action") or "")[:128],
            "actionDatetime": event_datetime.isoformat() if event_datetime else None,
        },
    )
    # Even if ROOK reports its own import complete, preserve our RUNNING state
    # until a Biopeak worker has normalized the corresponding documents.
    upstream_import_complete = any(token in text for token in ("import completed", "historical completed"))
    if (upstream_import_complete and connection.connection_method == "api"
            and connection.authorization_status == AuthorizationStatus.AUTHORIZED
            and connection.import_status == HistoricalImportStatus.RUNNING):
        enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=f"notification-import-verification:{connection.pk}:{receipt.pk}",
            customer_profile=connection.customer_profile,
            connection=connection,
        )
    if (
        not resumed
        and connection.status in {ConnectionStatus.IMPORTING, ConnectionStatus.HISTORICAL_REIMPORT}
        and connection.authorization_status == AuthorizationStatus.AUTHORIZED
        and previous_status not in {ConnectionStatus.IMPORTING, ConnectionStatus.HISTORICAL_REIMPORT}
        and connection.connection_method == "api"
    ):
        enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=(f"notification-connect-recovery:{connection.pk}:"
                             f"{timezone.localdate().isoformat()}"),
            customer_profile=connection.customer_profile,
            connection=connection,
        )
    if connection.status == ConnectionStatus.PROVIDER_ERROR:
        enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=(
                f"notification-recovery:{connection.pk}:"
                f"{timezone.localdate().isoformat()}"
            ),
            customer_profile=connection.customer_profile,
            connection=connection,
        )
    return {
        "accepted": True,
        "connectionId": str(connection.pk),
        "status": connection.status,
    }

