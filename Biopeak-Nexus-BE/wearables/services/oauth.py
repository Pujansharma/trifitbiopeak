"""Server-managed ROOK authorization handoff with a one-use, expiring CSRF state.

The OAuth provider never authenticates the Biopeak member. We match the
opaque return state to a connection already initiated by an authenticated
Biopeak member and verify ROOK authorization server-to-server. The public
callback returns no user, token, or health information.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from wearables.models import WearableConnectionEvent
from wearables.services.client import RookClient, RookConfigurationError, RookServiceError
from wearables.utils.constants import AuthorizationStatus, ConnectionStatus


class OAuthStateError(ValueError):
    pass


def callback_url_configured() -> bool:
    return bool(getattr(settings, "ROOK_CALLBACK_URL", ""))


def callback_url_for_connection(
    connection, *, actor_user, correlation_id="", previous_status: str | None = None,
) -> str | None:
    """Make a short, one-time callback URL compatible with ROOK's authorizer.

    ROOK's redirect_url limit is 50 characters; it appends
    /client_uuid/{client_uuid}/user_id/{user_id} to the redirect_url path.
    Operator config must be an HTTPS origin plus /r, without a query string.
    Store only a digest of the random path nonce, never a plaintext token.
    """
    callback = getattr(settings, "ROOK_CALLBACK_URL", "").strip()
    if not callback:
        return None  # Authenticated device status polling is the supported fallback.
    parsed = urlsplit(callback)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
        or parsed.fragment or parsed.query or parsed.path.rstrip("/") != "/r"
        or parsed.port is not None
    ):
        raise RookConfigurationError(
            "ROOK_CALLBACK_URL must be a short HTTPS URL ending in /r, "
            "with no query, credentials, fragment, or explicit port."
        )
    nonce = secrets.token_urlsafe(12)  # 96 bits; 16 URL-safe characters.
    redirect_url = f"{callback.rstrip('/')}/{nonce}"
    if len(redirect_url) > 50:
        raise RookConfigurationError(
            "ROOK_CALLBACK_URL is too long. The complete redirect URL, "
            "including its one-time state token, must be at most 50 characters."
        )
    digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    WearableConnectionEvent.objects.create(
        connection=connection,
        event_type="oauth_state_pending",
        previous_status=(connection.status if previous_status is None else previous_status),
        current_status=connection.status,
        actor_user=actor_user,
        correlation_id=correlation_id[:128],
        detail="One-time ROOK OAuth callback state registered.",
        payload={"nonceDigest": digest, "source": connection.data_source},
    )
    return redirect_url


def retire_oauth_callback_state(connection, callback_url: str | None, *, event_type: str) -> None:
    """Invalidate an unreturned or already-handled callback without touching old links."""
    if not callback_url:
        return
    nonce = urlsplit(callback_url).path.rsplit("/", 1)[-1]
    digest = hashlib.sha256(nonce.encode("utf-8")).hexdigest()
    WearableConnectionEvent.objects.filter(
        connection=connection,
        event_type="oauth_state_pending",
        payload__nonceDigest=digest,
    ).update(event_type=event_type, updated_at=timezone.now())


def _decode_state(state: str) -> str:
    if (
        not isinstance(state, str) or len(state) != 16
        or not all(c.isascii() and (c.isalnum() or c in "-_" ) for c in state)
    ):
        raise OAuthStateError("Invalid authorization state.")
    return hashlib.sha256(state.encode("utf-8")).hexdigest()


def _cancel_pending_connection(connection, *, reason: str, prior_status: str = "") -> None:
    # A failed *new* authorization must never disconnect an already-active
    # provider or delete historical health data.
    if connection.status not in (ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING):
        return
    if prior_status in (ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL, ConnectionStatus.IDLE):
        from wearables.services.connections import save_connection_transition
        save_connection_transition(
            connection, status=prior_status, authorization_status=AuthorizationStatus.AUTHORIZED,
            event_type="oauth_reauthorization_cancelled", detail=reason,
        )
        return
    if prior_status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED):
        from wearables.services.connections import save_connection_transition
        save_connection_transition(
            connection, status=prior_status,
            authorization_status=(AuthorizationStatus.REVOKED if prior_status == ConnectionStatus.DISCONNECTED
                                  else AuthorizationStatus.EXPIRED),
            event_type="oauth_reconnection_cancelled", detail=reason,
        )
        return
    from wearables.services.connections import save_connection_transition
    save_connection_transition(
        connection,
        status=ConnectionStatus.NEVER_CONNECTED,
        authorization_status=AuthorizationStatus.DENIED,
        event_type="oauth_authorization_cancelled",
        detail=reason,
    )


def complete_oauth_callback(
    state_token: str, *, rook_client_uuid: str, rook_user_id: str, cancelled: bool = False
) -> str:
    """Consume an opaque path state only after a ROOK server-side auth check.

    Verify *both* ROOK-appended path identifiers against server settings and
    the member's stored ROOK identity before querying the authorization API.
    """
    digest = _decode_state(state_token)
    configured_client_uuid = str(getattr(settings, "ROOK_CLIENT_UUID", ""))
    if not configured_client_uuid or not hmac.compare_digest(configured_client_uuid, str(rook_client_uuid)):
        raise OAuthStateError("ROOK client identity does not match.")
    with transaction.atomic():
        event = (
            WearableConnectionEvent.objects.select_for_update()
            .select_related("connection__identity")
            .filter(event_type="oauth_state_pending", payload__nonceDigest=digest)
            .first()
        )
        if event is None:
            raise OAuthStateError("Authorization state is unknown or already used.")
        connection = event.connection
        expected_rook_user_id = connection.identity.rook_user_id
        if not hmac.compare_digest(expected_rook_user_id, str(rook_user_id)):
            raise OAuthStateError("ROOK member identity does not match.")
        age = timezone.now() - event.created_at
        max_age = timedelta(minutes=max(1, getattr(settings, "ROOK_OAUTH_TIMEOUT_MINUTES", 15)))
        if age > max_age:
            event.event_type = "oauth_state_expired"
            event.save(update_fields=["event_type", "updated_at"])
            _cancel_pending_connection(connection, reason="ROOK authorization expired.", prior_status=event.previous_status)
            return "expired"
        if cancelled:
            event.event_type = "oauth_state_cancelled"
            event.save(update_fields=["event_type", "updated_at"])
            _cancel_pending_connection(connection, reason="Member cancelled authorization.", prior_status=event.previous_status)
            return "cancelled"
        # The browser path is never proof of authorization. ROOK is authoritative.
        authorized = RookClient().get_authorized_sources(
            rook_user_id=expected_rook_user_id
        )
        if connection.data_source not in authorized:
            # ROOK may be eventually consistent: status-polling remains available.
            return "pending"
        # A verified upstream grant is not enough to finish the local attempt:
        # the connection transition and recovery job must commit together with
        # consuming the one-time callback state. Otherwise a transient database
        # error can burn the callback while the UI remains "Authorizing".
        from wearables.services.connections import authorization_confirmed
        from wearables.models import WearableConnection

        connection = WearableConnection.objects.select_for_update().get(pk=connection.pk)
        if connection.status in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}:
            was_reconnect = event.previous_status in {
                ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED,
            }
            authorization_confirmed(
                connection, was_reconnect=was_reconnect,
                actor_user=event.actor_user, correlation_id=event.correlation_id,
            )
        elif connection.authorization_status != AuthorizationStatus.AUTHORIZED:
            # Disconnect/cancellation raced the external ROOK check. Never
            # override the local member's explicit revocation with a late page.
            event.event_type = "oauth_state_superseded"
            event.save(update_fields=["event_type", "updated_at"])
            return "cancelled"
        # A status poll may have completed the grant first; that is already a
        # success, and this callback must not trigger another historical import.
        event.event_type = "oauth_state_verified"
        event.save(update_fields=["event_type", "updated_at"])
        return "authorized"


def expire_oauth_attempts(customer_profile) -> int:
    """Expire stale handoffs during an authenticated device status refresh."""
    cutoff = timezone.now() - timedelta(minutes=max(1, getattr(settings, "ROOK_OAUTH_TIMEOUT_MINUTES", 15)))
    pending = list(
        WearableConnectionEvent.objects.select_related("connection").filter(
            connection__customer_profile=customer_profile,
            event_type="oauth_state_pending",
            created_at__lt=cutoff,
        )
    )
    for event in pending:
        with transaction.atomic():
            changed = WearableConnectionEvent.objects.filter(
                pk=event.pk, event_type="oauth_state_pending"
            ).update(event_type="oauth_state_expired", updated_at=timezone.now())
            if changed:
                _cancel_pending_connection(event.connection, reason="ROOK authorization timed out.", prior_status=event.previous_status)
    return len(pending)
