"""Phase 1 connection-state and source-ingestion rules (PRD 10.1/10.2).

Keeping these rules in the wearable module protects the original client backend.
A ROOK identity/consent is never sufficient to authorize an individual source.
"""
from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    PermissionStatus,
)

CONNECTED_STATES = frozenset({
    ConnectionStatus.IMPORTING, ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL,
    ConnectionStatus.IDLE, ConnectionStatus.RECONNECTED,
    ConnectionStatus.HISTORICAL_REIMPORT, ConnectionStatus.PROVIDER_ERROR,
})

# The transitions below also allow deliberate re-authorization and explicit
# disconnect from an incomplete connection. All state mutations from our module
# must follow this graph; unexpected event ordering is ignored at webhook edges.
ALLOWED_TRANSITIONS = {
    ConnectionStatus.NEVER_CONNECTED: {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING, ConnectionStatus.IMPORTING, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED},
    ConnectionStatus.CONNECTING: {ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.AUTHORIZING, ConnectionStatus.IMPORTING, ConnectionStatus.RECONNECTED, ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL, ConnectionStatus.NEVER_CONNECTED, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED},
    ConnectionStatus.AUTHORIZING: {ConnectionStatus.NEVER_CONNECTED, ConnectionStatus.IMPORTING, ConnectionStatus.RECONNECTED, ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL, ConnectionStatus.IDLE},
    ConnectionStatus.PERMISSION_DENIED: {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING, ConnectionStatus.IMPORTING, ConnectionStatus.RECONNECTED, ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED},
    ConnectionStatus.IMPORTING: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING},
    ConnectionStatus.ACTIVE: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.DISCONNECTED, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.IMPORTING, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING},
    ConnectionStatus.PARTIAL: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.IMPORTING, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.DISCONNECTED, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING},
    ConnectionStatus.IDLE: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.PARTIAL, ConnectionStatus.IMPORTING, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.DISCONNECTED, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING},
    ConnectionStatus.AUTHORIZATION_EXPIRED: {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING, ConnectionStatus.RECONNECTED, ConnectionStatus.DISCONNECTED, ConnectionStatus.PROVIDER_ERROR},
    ConnectionStatus.DISCONNECTED: {ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING, ConnectionStatus.RECONNECTED},
    ConnectionStatus.RECONNECTED: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.HISTORICAL_REIMPORT, ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED, ConnectionStatus.PARTIAL},
    ConnectionStatus.HISTORICAL_REIMPORT: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL, ConnectionStatus.PROVIDER_ERROR, ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED},
    ConnectionStatus.PROVIDER_ERROR: {ConnectionStatus.PERMISSION_DENIED, ConnectionStatus.ACTIVE, ConnectionStatus.IDLE, ConnectionStatus.PARTIAL, ConnectionStatus.IMPORTING, ConnectionStatus.HISTORICAL_REIMPORT, ConnectionStatus.AUTHORIZATION_EXPIRED, ConnectionStatus.DISCONNECTED, ConnectionStatus.CONNECTING, ConnectionStatus.AUTHORIZING},
}


def valid_transition(previous_status: str, next_status: str) -> bool:
    return previous_status == next_status or next_status in ALLOWED_TRANSITIONS.get(previous_status, set())


def can_ingest_source(connection) -> bool:
    """Whether an individual *previously authorized* provider may add data.

    Positive notifications cannot silently override an expired/revoked grant.
    A recovering provider in PROVIDER_ERROR is allowed only if authorization
    itself remains valid (an error may be transport-related rather than auth).
    """
    return (
        connection.status in CONNECTED_STATES
        and connection.authorization_status == AuthorizationStatus.AUTHORIZED
        and connection.permission_status != PermissionStatus.DENIED
        and connection.disconnected_at is None
        and connection.last_error_code != "provider_account_closed"
    )


def source_permission_for_domain(connection, domain: str) -> str:
    """Return granted / denied / unknown / unsupported for one connection+domain.

    `capabilities` on the native-status API represent the *granted* health
    domains, not ROOK's global provider support matrix. Missing grants must
    not be mislabeled as provider-level Unsupported.
    """
    if connection.status in {ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED}:
        return "denied"
    if connection.permission_status == PermissionStatus.DENIED:
        return "denied"
    capabilities = {str(c).lower() for c in (connection.capabilities or [])}
    if connection.permission_status == PermissionStatus.LIMITED:
        return "granted" if domain in capabilities else "denied"
    if capabilities:
        return "granted" if domain in capabilities else "denied"
    if connection.permission_status == PermissionStatus.GRANTED:
        return "granted"
    return "unknown"
