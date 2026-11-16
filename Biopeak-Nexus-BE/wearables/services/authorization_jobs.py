"""Manager flow: queued authorization verification and queued remote revocation."""
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from wearables.services.coordination import serialize_profile_changes, serialize_connection_changes

from accounts.customers.models import CustomerProfile
from wearables.models import RookOutbox, WearableConnection, WearableConnectionEvent
from wearables.services.client import RookClient, RookServiceError
from wearables.services.consent import has_active_wearable_consent
from wearables.services.connections import (
    authorization_confirmed, refresh_authorizing_connections, save_connection_transition,
)
from wearables.services.job_claims import assert_health_job_owned, heartbeat_health_job, checkpoint_health_job
from wearables.services.progress_policy import revocation_confirmation_policy
from wearables.services.runtime import integer_setting
from wearables.utils.constants import AuthorizationStatus, ConnectionStatus, HistoricalImportStatus


def process_authorise_rook_connection(job: RookOutbox) -> dict:
    if job.connection_id is None:
        if job.customer_profile_id is None:
            raise ValueError("Authorization job has no customer profile or connection.")
        refresh_authorizing_connections(job.customer_profile)
        return {"verificationQueued": True}
    connection = (
        WearableConnection.objects.select_related("identity", "customer_profile")
        .filter(pk=job.connection_id)
        .first()
    )
    if connection is None:
        return {"skipped": True, "reason": "connection_missing"}
    generation = job.payload.get("generation")
    if generation != str(connection.authorization_generation):
        return {"skipped": True, "reason": "authorization_superseded"}
    if connection.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}:
        return {"skipped": True, "reason": "authorization_no_longer_pending"}
    if not has_active_wearable_consent(connection.customer_profile):
        return {"skipped": True, "reason": "consent_revoked"}
    heartbeat_health_job(job)
    timeout = timedelta(minutes=max(1, getattr(settings, "ROOK_OAUTH_TIMEOUT_MINUTES", 15)))
    try:
        sources = RookClient().get_authorized_sources(rook_user_id=connection.identity.rook_user_id)
    except RookServiceError as error:
        # Authorized-sources lookup documents 422 for a user not created yet.
        # Await the interactive handoff within its existing bounded deadline.
        if error.status_code != 422:
            raise
        sources = set()
    heartbeat_health_job(job)
    with transaction.atomic():
        serialize_profile_changes(connection.customer_profile_id)
        current = serialize_connection_changes(connection.pk)
        assert_health_job_owned(job)
        if (str(current.authorization_generation) != generation
                or current.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}):
            return {"skipped": True, "reason": "authorization_superseded"}
        if not has_active_wearable_consent(current.customer_profile):
            return {"skipped": True, "reason": "consent_revoked"}
        if current.data_source not in sources:
            if timezone.now() < job.created_at + timeout:
                return {"deferred": True, "reason": "authorization_pending", "retryAfterSeconds": 30}
            save_connection_transition(
                current, status=(ConnectionStatus.AUTHORIZATION_EXPIRED if job.payload.get("wasReconnect")
                                 else ConnectionStatus.NEVER_CONNECTED),
                authorization_status=(AuthorizationStatus.EXPIRED if job.payload.get("wasReconnect")
                                      else AuthorizationStatus.DENIED),
                import_status=HistoricalImportStatus.NOT_STARTED,
                event_type="authorization_verification_expired",
                detail="Provider grant not confirmed; user must retry authorization.",
            )
            return {"authorizationFailed": True, "reason": "authorization_expired", "userAction": "reconnect"}
        authorization_confirmed(current, was_reconnect=bool(job.payload.get("wasReconnect")))
        WearableConnectionEvent.objects.filter(
            connection=current, event_type__in=("oauth_state_pending", "oauth_state_queued"),
        ).update(event_type="oauth_state_verified", updated_at=timezone.localtime())
    return {"authorized": True, "initialSyncQueued": True}



def verify_rook_connection_now(
    connection: WearableConnection, *, was_reconnect: bool = False,
    actor_user=None, correlation_id: str = "",
) -> dict:
    """Verify a pending ROOK grant in this request; never enqueue auth work."""
    connection = (
        WearableConnection.objects.select_related("identity", "customer_profile")
        .filter(pk=connection.pk).first()
    )
    if connection is None:
        return {"authorized": False, "reason": "connection_missing"}
    generation = str(connection.authorization_generation)
    if connection.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}:
        return {
            "authorized": connection.authorization_status == AuthorizationStatus.AUTHORIZED,
            "reason": "authorization_no_longer_pending",
        }
    if connection.connection_method != "api":
        return {"authorized": False, "reason": "not_api_connection"}
    if not has_active_wearable_consent(connection.customer_profile):
        return {"authorized": False, "reason": "consent_revoked"}

    try:
        sources = RookClient().get_authorized_sources(
            rook_user_id=connection.identity.rook_user_id,
        )
    except RookServiceError as error:
        if error.status_code == 422:
            return {"authorized": False, "reason": "authorization_pending", "retryRequired": True}
        raise

    if connection.data_source not in sources:
        return {"authorized": False, "reason": "provider_not_authorized", "retryRequired": True}

    with transaction.atomic():
        serialize_profile_changes(connection.customer_profile_id)
        current = serialize_connection_changes(connection.pk)
        if (str(current.authorization_generation) != generation
                or current.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}):
            return {"authorized": False, "reason": "authorization_superseded"}
        if not has_active_wearable_consent(current.customer_profile):
            return {"authorized": False, "reason": "consent_revoked"}
        authorization_confirmed(
            current, was_reconnect=was_reconnect, actor_user=actor_user,
            correlation_id=correlation_id,
        )
        WearableConnectionEvent.objects.filter(
            connection=current,
            event_type__in=("oauth_state_pending", "oauth_state_verification_pending", "oauth_state_queued"),
        ).update(event_type="oauth_state_verified", updated_at=timezone.localtime())
    return {"authorized": True, "initialSyncQueued": True}

def process_revoke_rook_connection(job: RookOutbox) -> dict:
    if job.connection_id is None:
        raise ValueError("Revocation job has no connection.")
    connection = (
        WearableConnection.objects.select_related("identity")
        .filter(pk=job.connection_id)
        .first()
    )
    if connection is None:
        return {"skipped": True, "reason": "connection_missing"}
    generation = job.payload.get("generation")
    # Older queued revokes had no generation. Only an explicitly disconnected
    # connection with a pending remote revoke can drain such a legacy row.
    if (connection.status != ConnectionStatus.DISCONNECTED
            or connection.last_error_code != "revoke_pending"
            or (generation and generation != str(connection.authorization_generation))):
        return {"skipped": True, "reason": "revocation_superseded_or_complete"}
    heartbeat_health_job(job)
    client = RookClient()
    checked = job.payload.get("revocationAuthorizationCheckedAt")
    requested_at = job.payload.get("revocationRequestedAt")
    fresh_check = (checked and not requested_at
                   and timezone.now() < datetime.fromisoformat(checked) + timedelta(minutes=5))
    sources = {connection.data_source} if fresh_check else client.get_authorized_sources(
        rook_user_id=connection.identity.rook_user_id,
    )
    heartbeat_health_job(job)
    if connection.data_source in sources:
        retry_seconds = 60
        if requested_at:
            policy = revocation_confirmation_policy(
                provider=connection.data_source, requested_at=datetime.fromisoformat(requested_at),
                now=timezone.localtime(),
                ordinary_minutes=integer_setting("ROOK_REVOKE_CONFIRMATION_MINUTES", 30, minimum=1, maximum=10080),
                withings_hours=integer_setting("ROOK_WITHINGS_REVOKE_CONFIRMATION_HOURS", 48, minimum=24, maximum=168),
            )
            if policy["expired"]:
                raise RookServiceError("ROOK has not confirmed remote revocation; local access remains blocked.")
            retry_seconds = policy["retryAfterSeconds"]
        else:
            if not fresh_check:
                checkpoint_health_job(
                    job,
                    {
                        **job.payload,
                        "revocationAuthorizationCheckedAt": timezone.localtime().isoformat(),
                    },
                )
            client.revoke_source(rook_user_id=connection.identity.rook_user_id, data_source=connection.data_source)
            checkpoint_health_job(
                job,
                {
                    **job.payload,
                    "revocationRequestedAt": timezone.localtime().isoformat(),
                },
            )
        return {"deferred": True, "reason": "awaiting_provider_revocation", "retryAfterSeconds": retry_seconds}
    with transaction.atomic():
        serialize_profile_changes(connection.customer_profile_id)
        current = serialize_connection_changes(connection.pk)
        assert_health_job_owned(job)
        if (current.status != ConnectionStatus.DISCONNECTED
                or current.authorization_generation != connection.authorization_generation):
            raise RookServiceError("Provider authorization changed during remote revocation.")
        current.last_error_code = ""
        current.last_error_detail = ""
        current.save(update_fields=["last_error_code", "last_error_detail", "updated_at"])
        WearableConnectionEvent.objects.create(
            connection=current, event_type="remote_revocation_completed",
            previous_status=current.status, current_status=current.status,
            payload={"generation": str(current.authorization_generation)},
        )
    return {"revoked": True}
