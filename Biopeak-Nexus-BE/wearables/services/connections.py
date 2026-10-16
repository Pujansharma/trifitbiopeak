from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from accounts.customers.models import CustomerProfile
from wearables.models import (
    RookMemberIdentity,
    WearableConnection,
    WearableConnectionEvent,
)
from wearables.services.client import (
    RookClient,
    RookConfigurationError,
    RookServiceError,
)
from wearables.services.identity import (
    get_or_create_rook_identity,
    record_wearable_consent,
)
from wearables.services.job_queue import enqueue_health_job
from wearables.services.lifecycle import valid_transition
from wearables.services.oauth import callback_url_for_connection, retire_oauth_callback_state
from wearables.utils.constants import (
    API_WEARABLE_SOURCES,
    NATIVE_WEARABLE_SOURCES,
    AuthorizationStatus,
    ConnectionMethod,
    ConnectionStatus,
    HealthJobType,
    HistoricalImportStatus,
    PermissionStatus,
)


def connection_method_for_source(data_source: str) -> str:
    if data_source in NATIVE_WEARABLE_SOURCES:
        return ConnectionMethod.SDK
    return ConnectionMethod.API


def record_connection_event(
    connection: WearableConnection,
    *,
    event_type: str,
    previous_status: str,
    actor_user=None,
    correlation_id: str = "",
    detail: str = "",
    payload: dict | None = None,
) -> WearableConnectionEvent:
    return WearableConnectionEvent.objects.create(
        connection=connection,
        event_type=event_type,
        previous_status=previous_status,
        current_status=connection.status,
        actor_user=actor_user,
        correlation_id=correlation_id,
        detail=detail[:512],
        payload=payload or {},
    )


def save_connection_transition(
    connection: WearableConnection,
    *,
    status: str,
    authorization_status: str | None = None,
    permission_status: str | None = None,
    import_status: str | None = None,
    actor_user=None,
    event_type: str,
    correlation_id: str = "",
    detail: str = "",
    payload: dict | None = None,
) -> WearableConnection:
    previous_status = connection.status
    if not valid_transition(previous_status, status):
        raise ValueError(f"Invalid wearable connection transition: {previous_status} -> {status}")
    connection.status = status
    update_fields = ["status", "updated_at"]
    optional_values = {
        "authorization_status": authorization_status,
        "permission_status": permission_status,
        "import_status": import_status,
    }
    for field_name, value in optional_values.items():
        if value is not None:
            setattr(connection, field_name, value)
            update_fields.append(field_name)
    connection.save(update_fields=update_fields)
    record_connection_event(
        connection,
        event_type=event_type,
        previous_status=previous_status,
        actor_user=actor_user,
        correlation_id=correlation_id,
        detail=detail,
        payload=payload,
    )
    # Device permission/status changes must never serve stale dashboard cards.
    from wearables.services.analytics import invalidate_health_dashboard
    invalidate_health_dashboard(connection.customer_profile)
    return connection


def get_or_create_connection(
    *,
    customer_profile: CustomerProfile,
    identity: RookMemberIdentity,
    data_source: str,
    historical_days_requested: int | None,
) -> WearableConnection:
    requested_days = (
        historical_days_requested
        if historical_days_requested is not None
        else min(
            getattr(settings, "ROOK_HISTORICAL_DAYS", 29),
            29 if data_source in NATIVE_WEARABLE_SOURCES else 7,
        )
    )
    connection, created = WearableConnection.objects.get_or_create(
        customer_profile=customer_profile,
        data_source=data_source,
        defaults={
            "identity": identity,
            "connection_method": connection_method_for_source(data_source),
            "historical_days_requested": requested_days,
        },
    )
    update_fields = []
    if connection.identity_id != identity.pk:
        connection.identity = identity
        update_fields.append("identity")
    if (
        historical_days_requested is not None
        and connection.historical_days_requested != historical_days_requested
    ):
        connection.historical_days_requested = historical_days_requested
        update_fields.append("historical_days_requested")
    if update_fields and not created:
        update_fields.append("updated_at")
        connection.save(update_fields=update_fields)
    return connection


@transaction.atomic
def prepare_connection(
    *,
    request,
    customer_profile: CustomerProfile,
    data_source: str,
    consent_version: str,
    historical_days_requested: int,
    timezone_name: str | None,
    preferred_units: str | None,
) -> WearableConnection:
    identity = get_or_create_rook_identity(
        customer_profile,
        timezone_name=timezone_name,
        preferred_units=preferred_units,
    )
    record_wearable_consent(
        request=request,
        customer_profile=customer_profile,
        consent_version=consent_version,
    )
    return get_or_create_connection(
        customer_profile=customer_profile,
        identity=identity,
        data_source=data_source,
        historical_days_requested=historical_days_requested,
    )


def authorization_confirmed(
    connection: WearableConnection, *, was_reconnect: bool = False,
    actor_user=None, correlation_id: str = "",
) -> WearableConnection:
    """Complete a verified ROOK authorization, then schedule bounded recovery.

    Only a ROOK server-side authorizer check or trusted native SDK status may
    call this helper. The callback URL/query params alone are never proof.
    """
    now = timezone.now()
    connection.connected_at = connection.connected_at or now
    connection.import_started_at = now
    connection.disconnected_at = None
    connection.last_error_code = ""
    connection.last_error_detail = ""
    connection.save(update_fields=[
        "connected_at", "import_started_at", "disconnected_at", "last_error_code",
        "last_error_detail", "updated_at",
    ])
    if was_reconnect:
        save_connection_transition(
            connection, status=ConnectionStatus.RECONNECTED,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            event_type="provider_reconnected", actor_user=actor_user,
            correlation_id=correlation_id,
        )
    save_connection_transition(
        connection,
        status=(ConnectionStatus.HISTORICAL_REIMPORT if was_reconnect else ConnectionStatus.IMPORTING),
        authorization_status=AuthorizationStatus.AUTHORIZED,
        import_status=HistoricalImportStatus.RUNNING,
        event_type="historical_reimport_started" if was_reconnect else "authorization_confirmed",
        actor_user=actor_user, correlation_id=correlation_id,
    )
    if connection.connection_method == ConnectionMethod.API:
        enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=f"authorization-recovery:{connection.pk}:{now.isoformat()}",
            customer_profile=connection.customer_profile,
            connection=connection,
        )
    return connection


def connection_attempt_origin(connection: WearableConnection) -> str:
    """Return the state before the *current* authorization attempt began.

    A repeated Connect tap must not turn a reconnect into a first-time link,
    even if the connection is already ``authorizing``.
    """
    if connection.status not in {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING}:
        return connection.status
    request_event = (
        WearableConnectionEvent.objects.filter(
            connection=connection, event_type="connection_requested",
        ).order_by("-created_at").first()
    )
    if request_event is not None and request_event.previous_status:
        return request_event.previous_status
    callback_event = (
        WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_pending",
        ).order_by("-created_at").first()
    )
    return callback_event.previous_status if callback_event is not None else connection.status


def start_connection(
    *,
    request,
    customer_profile: CustomerProfile,
    validated_data: dict,
    correlation_id: str = "",
) -> dict:
    data_source = validated_data["data_source"]
    connection = prepare_connection(
        request=request,
        customer_profile=customer_profile,
        data_source=data_source,
        consent_version=validated_data["consent_version"],
        historical_days_requested=validated_data["historical_days"],
        timezone_name=validated_data.get("timezone_name"),
        preferred_units=validated_data.get("preferred_units"),
    )
    # Idempotent second link: never trigger pre-existing recovery twice merely
    # because the member tapped the connect button again (PRD EC-043).
    if (connection.status in {ConnectionStatus.ACTIVE, ConnectionStatus.IDLE,
                              ConnectionStatus.PARTIAL, ConnectionStatus.IMPORTING,
                              ConnectionStatus.RECONNECTED, ConnectionStatus.HISTORICAL_REIMPORT}
            and connection.authorization_status == AuthorizationStatus.AUTHORIZED):
        return {"connection": connection, "authorization_method": connection.connection_method,
                "authorization_url": None}
    pending_authorization = connection.status in {
        ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING,
    }
    origin_status = connection_attempt_origin(connection)
    was_reconnect = origin_status in {
        ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED,
    }
    if connection.last_error_code == "provider_account_closed":
        raise ValueError("ROOK reports that this upstream account was closed. Connect a different provider.")
    connection.last_error_code = ""
    connection.last_error_detail = ""
    # Keep a disconnected provider closed until ROOK/SDK actually authorizes.
    # Otherwise a delayed webhook can race ahead of the authorization screen.
    connection.save(
        update_fields=[
            "last_error_code",
            "last_error_detail",
            "updated_at",
        ]
    )
    if data_source in NATIVE_WEARABLE_SOURCES:
        if pending_authorization:
            # The native SDK owns its permission screen; a second tap is a no-op.
            return {
                "connection": connection,
                "authorization_method": ConnectionMethod.SDK,
                "authorization_url": None,
            }
        save_connection_transition(
            connection,
            status=ConnectionStatus.CONNECTING,
            authorization_status=AuthorizationStatus.PENDING,
            permission_status=PermissionStatus.NOT_DETERMINED,
            import_status=HistoricalImportStatus.NOT_STARTED,
            actor_user=request.user,
            event_type="connection_requested",
            correlation_id=correlation_id,
            detail="Native SDK authorization requested.",
            payload={"reconnect": was_reconnect},
        )
        return {
            "connection": connection,
            "authorization_method": ConnectionMethod.SDK,
            "authorization_url": None,
        }

    previous_callback_ids = list(
        WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_pending",
        ).values_list("pk", flat=True)
    )
    callback_url = callback_url_for_connection(
        connection,
        actor_user=request.user,
        correlation_id=correlation_id,
        previous_status=origin_status,
    )
    if not pending_authorization:
        save_connection_transition(
            connection, status=ConnectionStatus.CONNECTING,
            authorization_status=AuthorizationStatus.PENDING,
            import_status=HistoricalImportStatus.NOT_STARTED,
            actor_user=request.user, event_type="connection_requested",
            correlation_id=correlation_id,
        )
    # A pending Authorizing -> Connecting transition is intentionally forbidden
    # by PRD 10.1. Re-issuing a link keeps the pending status unchanged.
    # Prefer a server-owned state-validated callback over arbitrary mobile redirects.
    client = RookClient()
    try:
        result = client.get_authorizer(
            rook_user_id=connection.identity.rook_user_id,
            data_source=data_source,
            redirect_url=callback_url or validated_data.get("redirect_url"),
        )
    except (RookConfigurationError, RookServiceError) as error:
        retire_oauth_callback_state(
            connection, callback_url, event_type="oauth_state_authorizer_failed",
        )
        connection.last_error_code = "rook_authorizer_failed"
        connection.last_error_detail = str(error)[:512]
        connection.save(
            update_fields=["last_error_code", "last_error_detail", "updated_at"]
        )
        if not pending_authorization and connection.status != ConnectionStatus.DISCONNECTED:
            save_connection_transition(
                connection,
                status=ConnectionStatus.PROVIDER_ERROR,
                authorization_status=AuthorizationStatus.ERROR,
                actor_user=request.user,
                event_type="authorization_failed",
                correlation_id=correlation_id,
                detail=str(error),
            )
        raise
    # Only a successfully issued new link supersedes an existing valid link.
    if previous_callback_ids:
        WearableConnectionEvent.objects.filter(
            pk__in=previous_callback_ids, event_type="oauth_state_pending",
        ).update(event_type="oauth_state_superseded", updated_at=timezone.now())
    connection.refresh_from_db()
    if connection.status in {
        ConnectionStatus.NEVER_CONNECTED, ConnectionStatus.DISCONNECTED,
        ConnectionStatus.AUTHORIZATION_EXPIRED,
    }:
        # A concurrent cancellation, disconnect or expiry cannot be undone by
        # a slow ROOK request finishing after the status was changed.
        retire_oauth_callback_state(connection, callback_url, event_type="oauth_state_superseded")
        return {"connection": connection, "authorization_method": ConnectionMethod.API,
                "authorization_url": None}
    if (connection.status in {ConnectionStatus.IMPORTING, ConnectionStatus.ACTIVE,
                              ConnectionStatus.PARTIAL, ConnectionStatus.IDLE,
                              ConnectionStatus.RECONNECTED, ConnectionStatus.HISTORICAL_REIMPORT}
            and connection.authorization_status == AuthorizationStatus.AUTHORIZED):
        retire_oauth_callback_state(connection, callback_url, event_type="oauth_state_superseded")
        return {"connection": connection, "authorization_method": ConnectionMethod.API,
                "authorization_url": None}
    authorized = result["authorized"]
    if authorized:
        retire_oauth_callback_state(connection, callback_url, event_type="oauth_state_verified")
        authorization_confirmed(
            connection, was_reconnect=was_reconnect,
            actor_user=request.user, correlation_id=correlation_id,
        )
    else:
        save_connection_transition(
            connection, status=ConnectionStatus.AUTHORIZING,
            authorization_status=AuthorizationStatus.PENDING,
            import_status=HistoricalImportStatus.NOT_STARTED,
            actor_user=request.user,
            event_type=("authorization_link_renewed" if pending_authorization
                        else "authorization_started"),
            correlation_id=correlation_id,
        )
    return {
        "connection": connection,
        "authorization_method": ConnectionMethod.API,
        "authorization_url": result["authorization_url"],
    }


def refresh_authorizing_connections(customer_profile: CustomerProfile) -> None:
    # Expire before checking ROOK: a callback received after its deadline
    # cannot revive an abandoned authorization attempt.
    from wearables.services.oauth import expire_oauth_attempts
    expire_oauth_attempts(customer_profile)
    connections = list(
        WearableConnection.objects.select_related("identity").filter(
            customer_profile=customer_profile,
            connection_method=ConnectionMethod.API,
            status__in=[ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING],
        )
    )
    if not connections:
        return
    authorized_sources = RookClient().get_authorized_sources(
        rook_user_id=connections[0].identity.rook_user_id
    )
    for connection in connections:
        if connection.data_source not in authorized_sources:
            continue
        was_reconnect = connection_attempt_origin(connection) in {
            ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED,
        }
        authorization_confirmed(connection, was_reconnect=was_reconnect)


def disconnect_connection(
    *,
    customer_profile: CustomerProfile,
    data_source: str,
    actor_user,
    correlation_id: str = "",
) -> tuple[WearableConnection | None, bool]:
    # Lock in the same identity -> connection order used during webhook
    # ingestion. The local authorization closes before any ROOK network call.
    with transaction.atomic():
        identity = RookMemberIdentity.objects.select_for_update().filter(
            customer_profile=customer_profile,
        ).first()
        if identity is None:
            return None, False
        connection = (
            WearableConnection.objects.select_for_update().select_related("identity")
            .filter(customer_profile=customer_profile, data_source=data_source)
            .first()
        )
        if connection is None:
            return None, False
        if connection.status == ConnectionStatus.DISCONNECTED:
            return connection, connection.last_error_code == "revoke_pending"
        connection.disconnected_at = timezone.now()
        connection.save(update_fields=["disconnected_at", "updated_at"])
        save_connection_transition(
            connection, status=ConnectionStatus.DISCONNECTED,
            authorization_status=AuthorizationStatus.REVOKED,
            permission_status=PermissionStatus.UNKNOWN,
            actor_user=actor_user, event_type="connection_revoked",
            correlation_id=correlation_id,
            detail="New ingestion stopped; previously recorded history retained.",
        )
    revoke_pending = False
    if connection.data_source in API_WEARABLE_SOURCES:
        try:
            RookClient().revoke_source(
                rook_user_id=connection.identity.rook_user_id,
                data_source=connection.data_source,
            )
        except (RookConfigurationError, RookServiceError) as error:
            revoke_pending = True
            # Never reopen the connection when upstream revocation fails.
            connection.last_error_code = "revoke_pending"
            connection.last_error_detail = str(error)[:512]
            connection.save(update_fields=["last_error_code", "last_error_detail", "updated_at"])
            enqueue_health_job(
                job_type=HealthJobType.REVOKE_CONNECTION,
                idempotency_key=f"revoke:{connection.pk}:{connection.disconnected_at.isoformat()}",
                customer_profile=customer_profile, connection=connection,
            )
    return connection, revoke_pending


def update_native_connection(
    *,
    customer_profile: CustomerProfile,
    actor_user,
    validated_data: dict,
    correlation_id: str = "",
) -> WearableConnection:
    existing_connection = WearableConnection.objects.filter(
        customer_profile=customer_profile,
        data_source=validated_data["data_source"],
        connection_method=ConnectionMethod.SDK,
    ).first()
    if existing_connection is None:
        raise ValueError("Start the native wearable connection before reporting status.")
    if existing_connection.status in {ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED}:
        raise ValueError("Start a new native authorization before updating a disconnected source.")
    identity = get_or_create_rook_identity(
        customer_profile,
        timezone_name=validated_data.get("timezone_name"),
    )
    connection = get_or_create_connection(
        customer_profile=customer_profile,
        identity=identity,
        data_source=validated_data["data_source"],
        historical_days_requested=validated_data.get(
            "historical_days",
            getattr(settings, "ROOK_HISTORICAL_DAYS", 29),
        ),
    )
    permission_status = validated_data["permission_status"]
    sdk_linked = validated_data["sdk_linked"]
    if "capabilities" in validated_data:
        connection.capabilities = validated_data["capabilities"]
    connection.last_error_code = ""
    connection.last_error_detail = ""
    connection.save(
        update_fields=[
            "capabilities",
            "last_error_code",
            "last_error_detail",
            "updated_at",
        ]
    )
    status = ConnectionStatus.CONNECTING
    authorization_status = AuthorizationStatus.PENDING
    import_status = HistoricalImportStatus.NOT_STARTED
    event_type = "native_status_updated"
    if permission_status == PermissionStatus.DENIED:
        status = ConnectionStatus.PERMISSION_DENIED
        authorization_status = AuthorizationStatus.DENIED
    elif sdk_linked and permission_status in {PermissionStatus.GRANTED, PermissionStatus.LIMITED}:
        previous_status = connection.status
        was_already_imported = connection.import_status == HistoricalImportStatus.COMPLETED
        status = ConnectionStatus.IMPORTING
        authorization_status = AuthorizationStatus.AUTHORIZED
        import_status = HistoricalImportStatus.RUNNING
        now = timezone.now()
        connection.connected_at = connection.connected_at or now
        connection.import_started_at = connection.import_started_at or now
        connection.disconnected_at = None
        connection.save(update_fields=["connected_at", "import_started_at", "disconnected_at", "updated_at"])
        reported_import_status = validated_data.get("historical_import_status")
        if previous_status == ConnectionStatus.CONNECTING and existing_connection.connected_at is not None:
            # Following device replacement, preserve the old timeline/baseline.
            status = ConnectionStatus.RECONNECTED
        elif previous_status == ConnectionStatus.HISTORICAL_REIMPORT:
            status = ConnectionStatus.HISTORICAL_REIMPORT
        if reported_import_status == HistoricalImportStatus.FAILED:
            status = ConnectionStatus.PROVIDER_ERROR
            import_status = HistoricalImportStatus.FAILED
        elif reported_import_status == HistoricalImportStatus.PARTIAL:
            status = ConnectionStatus.PARTIAL
            import_status = HistoricalImportStatus.PARTIAL
        elif reported_import_status == HistoricalImportStatus.COMPLETED or (
            was_already_imported and reported_import_status is None
        ):
            # EC-013: later permission grants must not restart completed imports.
            status = (ConnectionStatus.PARTIAL if permission_status == PermissionStatus.LIMITED
                      else ConnectionStatus.ACTIVE)
            import_status = HistoricalImportStatus.COMPLETED
            connection.import_completed_at = timezone.now()
            connection.save(update_fields=["import_completed_at", "updated_at"])
        event_type = "native_authorization_confirmed"
    if status == ConnectionStatus.RECONNECTED:
        save_connection_transition(
            connection, status=ConnectionStatus.RECONNECTED,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            permission_status=permission_status,
            event_type="native_reconnected", actor_user=actor_user,
            correlation_id=correlation_id,
        )
        status = ConnectionStatus.HISTORICAL_REIMPORT
    return save_connection_transition(
        connection,
        status=status,
        authorization_status=authorization_status,
        permission_status=permission_status,
        import_status=import_status,
        actor_user=actor_user,
        event_type=event_type,
        correlation_id=correlation_id,
    )


def connection_experience_state(connection: WearableConnection) -> str:
    # A source that has never produced a measurement can still become stale.
    # Use the authorization time until a successful sync timestamp exists.
    latest_activity = connection.last_successful_sync or connection.connected_at
    if (
        connection.status in {ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL}
        and latest_activity is not None
        and latest_activity < timezone.now()
        - timedelta(hours=getattr(settings, "ROOK_SYNC_DELAY_HOURS", 48))
    ):
        return "sync_delayed"
    return connection.status


def connection_actions(connection: WearableConnection) -> list[dict]:
    if connection.last_error_code == "provider_account_closed":
        return [{"id": "connect_another_provider", "label": "Connect Another Provider"}]
    status = connection_experience_state(connection)
    action_map = {
        ConnectionStatus.PERMISSION_DENIED: [
            {"id": "grant_permission", "label": "Grant Permission"}
        ],
        ConnectionStatus.AUTHORIZATION_EXPIRED: [
            {"id": "reconnect", "label": "Reconnect"}
        ],
        ConnectionStatus.DISCONNECTED: [
            {"id": "reconnect", "label": "Reconnect"}
        ],
        ConnectionStatus.PROVIDER_ERROR: [
            {"id": "retry_sync", "label": "Retry Sync"}
        ],
        "sync_delayed": [{"id": "retry_sync", "label": "Retry Sync"}],
    }
    return action_map.get(status, [])


def serialize_connection(connection: WearableConnection) -> dict:
    return {
        "id": str(connection.pk),
        "provider": connection.data_source,
        "connectionMethod": connection.connection_method,
        "status": connection.status,
        "experienceState": connection_experience_state(connection),
        "authorizationStatus": connection.authorization_status,
        "permissionStatus": connection.permission_status,
        "importStatus": connection.import_status,
        "capabilities": connection.capabilities,
        "connectedAt": connection.connected_at,
        "disconnectedAt": connection.disconnected_at,
        "lastSuccessfulSync": connection.last_successful_sync,
        "lastWebhookReceivedAt": connection.last_webhook_received_at,
        "historicalDaysRequested": connection.historical_days_requested,
        "availableFrom": connection.available_from,
        "availableTo": connection.available_to,
        "lastError": (
            {
                "code": connection.last_error_code,
                "detail": connection.last_error_detail,
            }
            if connection.last_error_code
            else None
        ),
        "actions": connection_actions(connection),
    }
