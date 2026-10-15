"""Profile-scoped consent revocation without deleting longitudinal history."""
from django.db import transaction
from django.utils import timezone

from wearables.models import WearableConnection, WearableConsent
from wearables.services.connections import API_WEARABLE_SOURCES, save_connection_transition
from wearables.services.job_queue import enqueue_health_job
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    ConsentStatus,
    HealthJobType,
    PermissionStatus,
)


@transaction.atomic
def revoke_profile_wearable_consent(*, customer_profile, actor_user, correlation_id: str = "") -> dict:
    """Stop further ingestion and queue external API disconnection; retain history.

    Revocation is recorded locally before the API response. Provider-side
    revocation is retried using the existing queue; its success is not promised.
    """
    now = timezone.now()
    consents = WearableConsent.objects.filter(
        customer_profile=customer_profile,
        status=ConsentStatus.GRANTED,
        revoked_at__isnull=True,
    )
    revoked_consents = consents.update(
        status=ConsentStatus.REVOKED,
        revoked_at=now,
        updated_at=now,
    )
    disconnected = 0
    revoke_jobs = 0
    connections = WearableConnection.objects.filter(customer_profile=customer_profile).select_related("identity")
    for connection in connections:
        if connection.status == ConnectionStatus.DISCONNECTED:
            continue
        connection.disconnected_at = now
        connection.save(update_fields=["disconnected_at", "updated_at"])
        save_connection_transition(
            connection,
            status=ConnectionStatus.DISCONNECTED,
            authorization_status=AuthorizationStatus.REVOKED,
            permission_status=PermissionStatus.UNKNOWN,
            actor_user=actor_user,
            event_type="consent_revoked",
            correlation_id=correlation_id,
            detail="New wearable ingestion blocked; historical health data retained pending policy.",
        )
        disconnected += 1
        if connection.data_source in API_WEARABLE_SOURCES:
            enqueue_health_job(
                job_type=HealthJobType.REVOKE_CONNECTION,
                idempotency_key=f"consent-revoke:{connection.pk}:{now.isoformat()}",
                customer_profile=customer_profile,
                connection=connection,
            )
            revoke_jobs += 1
    return {
        "consentsRevoked": revoked_consents,
        "connectionsDisconnected": disconnected,
        "upstreamRevocationJobsQueued": revoke_jobs,
        "historyRetained": True,
    }
