"""Authorization epochs live in existing audit events, independent of sync runs."""
from django.db import transaction

from wearables.models import WearableConnection, WearableConnectionEvent
from wearables.services.analytics import invalidate_health_dashboard
from wearables.services.coordination import serialize_connection_changes
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    HistoricalImportStatus,
)


def record_authorization_grant(connection: WearableConnection):
    generation = str(connection.authorization_generation)
    if not WearableConnectionEvent.objects.filter(
        connection=connection, event_type="authorization_granted", payload__generation=generation,
    ).exists():
        WearableConnectionEvent.objects.create(
            connection=connection, event_type="authorization_granted",
            previous_status=connection.status, current_status=connection.status,
            payload={"generation": generation},
        )


def authorization_granted_at(connection: WearableConnection):
    return WearableConnectionEvent.objects.filter(
        connection=connection, event_type="authorization_granted",
        payload__generation=str(connection.authorization_generation),
    ).order_by("created_at").values_list("created_at", flat=True).first()


def mark_authorization_failed(connection: WearableConnection, *, generation: str, detail: str):
    """Only the current pending grant may fail; explicit Connect starts a new one."""
    with transaction.atomic():
        current = serialize_connection_changes(connection.pk)
        if (str(current.authorization_generation) != generation
                or current.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}):
            return False
        previous_status = current.status
        current.status = ConnectionStatus.PROVIDER_ERROR
        current.authorization_status = AuthorizationStatus.ERROR
        current.import_status = HistoricalImportStatus.NOT_STARTED
        current.last_error_code = "authorization_verification_failed"
        current.last_error_detail = detail[:512]
        current.save(update_fields=["status", "authorization_status", "import_status",
                                    "last_error_code", "last_error_detail", "updated_at"])
        WearableConnectionEvent.objects.create(
            connection=current, event_type="authorization_verification_failed",
            previous_status=previous_status, current_status=current.status,
            detail=detail[:512], payload={"generation": generation},
        )
        invalidate_health_dashboard(current.customer_profile)
        return True
