"""Consent revocation without changing the client's customer/auth schemas."""
from django.utils import timezone
from wearables.models import WearableConsent, WearableConnection
from wearables.services.connections import disconnect_connection
from wearables.utils.constants import ConsentStatus, ConnectionStatus


def has_active_wearable_consent(customer_profile) -> bool:
    return WearableConsent.objects.filter(
        customer_profile=customer_profile, status=ConsentStatus.GRANTED,
        revoked_at__isnull=True,
    ).exists()


def revoke_wearable_consent(*, customer_profile, actor_user, correlation_id="") -> dict:
    """Revoke ingestion consent and all live connections, retaining past history."""
    connections = list(WearableConnection.objects.filter(customer_profile=customer_profile))
    failed_revoke = []
    for connection in connections:
        if connection.status == ConnectionStatus.DISCONNECTED:
            continue
        _, pending = disconnect_connection(
            customer_profile=customer_profile, data_source=connection.data_source,
            actor_user=actor_user, correlation_id=correlation_id,
        )
        if pending:
            failed_revoke.append(connection.data_source)
    count = WearableConsent.objects.filter(
        customer_profile=customer_profile, status=ConsentStatus.GRANTED,
        revoked_at__isnull=True,
    ).update(status=ConsentStatus.REVOKED, revoked_at=timezone.now(), updated_at=timezone.now())
    return {
        "revokedConsentRecords": count,
        "historyRetained": True,
        "revokePendingProviders": failed_revoke,
    }
