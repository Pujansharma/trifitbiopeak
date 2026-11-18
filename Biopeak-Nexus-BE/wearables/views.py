import uuid

from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import NotFound
from rest_framework.throttling import ScopedRateThrottle

from accounts.organizations.utils.constants import FeatureTabOptions
from accounts.utils.permissions import IsCustomerUser
from core.utils.views.main import BaseGenericAPIView
from wearables.models import RookMemberIdentity, WearableConnection
from wearables.serializers import (
    DeviceConnectSerializer,
    DeviceDisconnectSerializer,
    DomainQuerySerializer,
    NativeDeviceStatusSerializer,
)
from wearables.services.analytics import (
    dashboard_payload,
    domain_payload,
)
from wearables.services.client import RookConfigurationError, RookServiceError
from wearables.services.config import provisioned_sources
from wearables.services.connections import (
    disconnect_connection,
    record_connection_event,
    refresh_authorizing_connections,
    serialize_connection,
    start_connection,
    update_native_connection,
)
from wearables.services.identity import resolve_customer_profile
from wearables.services.consent import has_active_wearable_consent
from wearables.services.job_queue import enqueue_or_reuse_fetch_rook_data_job
from wearables.services.sync_policy import ManualSyncCooldown, next_manual_sync_at
from wearables.services.provider_errors import RookRequestDeferred
from wearables.services.rate_policy import seconds_until
from wearables.services.progress import attach_connection_progress
from django.utils import timezone
from wearables.utils.constants import (HEALTH_DOMAIN_ORDER, ConnectionMethod, ConnectionStatus,
    AuthorizationStatus, HealthJobType, HistoricalImportStatus, WearableSource, NATIVE_WEARABLE_SOURCES)


class WearablesAPIView(BaseGenericAPIView):
    permission_classes = (IsCustomerUser,)

    def ensure_profile_feature_enabled(self, customer_profile) -> None:
        if not getattr(settings, "WEARABLES_REQUIRE_PROFILE_FEATURE", False):
            return
        feature = getattr(customer_profile, "feature", None)
        if feature is None or FeatureTabOptions.WEARABLES not in feature.enabled_tabs:
            raise NotFound("Wearable integration is not enabled for this profile.")

    def get_customer_profile(self):
        customer_profile = resolve_customer_profile(self.request)
        self.ensure_profile_feature_enabled(customer_profile)
        return customer_profile

    def correlation_id(self) -> str:
        return self.request.headers.get("X-Correlation-ID") or str(uuid.uuid4())


class DeviceConnectView(WearablesAPIView):
    serializer_class = DeviceConnectSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_connect"

    @extend_schema(responses={201: OpenApiTypes.OBJECT})
    def post(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            result = start_connection(
                request=request,
                customer_profile=customer_profile,
                validated_data=serializer.validated_data,
                correlation_id=self.correlation_id(),
            )
        except ValueError as error:
            self.raise_bad_request(str(error))
        except RookConfigurationError as error:
            return self.send_response(str(error), status=503)
        except RookRequestDeferred as error:
            response = self.send_response(error.detail, {"retryAt": error.retry_at}, status=429)
            response["Retry-After"] = str(seconds_until(error.retry_at, timezone.localtime()))
            return response
        except RookServiceError as error:
            return self.send_response(error.detail, status=error.status_code)
        connection = result["connection"]
        data = {
            "connection": serialize_connection(connection),
            "authorizationMethod": result["authorization_method"],
            "authorizationUrl": result["authorization_url"],
            "rookUserId": connection.identity.rook_user_id,
        }
        requested_days = serializer.requested_historical_days
        applied_days = serializer.validated_data["historical_days"]
        history = {
            "requestedDays": requested_days,
            "appliedDays": applied_days,
            "maxSupportedDays": serializer.max_historical_days,
            "adjusted": requested_days != applied_days,
        }
        if serializer.history_disabled_by_policy:
            history["notice"] = (
                "Pre-existing data import is disabled for this deployment; "
                "live sync begins now and history builds forward."
            )
        elif requested_days != applied_days:
            history["notice"] = (
                f"{serializer.validated_data['data_source']} supports at most "
                f"{serializer.max_historical_days} days of pre-existing "
                f"history through this ROOK connection. "
                f"Requested {requested_days} days; using {applied_days} days."
            )
        data["historicalImport"] = history
        return self.send_response("Wearable connection initiated.", data, status=201)


class DeviceDisconnectView(WearablesAPIView):
    serializer_class = DeviceDisconnectSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_connect"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def post(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        connection, revoke_pending = disconnect_connection(
            customer_profile=customer_profile,
            data_source=serializer.validated_data["data_source"],
            actor_user=request.user,
            correlation_id=self.correlation_id(),
        )
        data = {
            "provider": serializer.validated_data["data_source"],
            "disconnected": True,
            "historyRetained": True,
            "upstreamRevokePending": revoke_pending,
            "connection": serialize_connection(connection) if connection else None,
        }
        return self.send_response("Wearable disconnected. History was retained.", data)


class DeviceProviderCatalogueView(WearablesAPIView):
    """List API providers and the profile's API/native connection statuses."""

    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()

        refresh_requested = str(
            request.query_params.get("refresh", "")
        ).lower() in {"1", "true"}

        refresh_error = None

        if refresh_requested:
            try:
                refresh_authorizing_connections(customer_profile)
            except (RookConfigurationError, RookServiceError) as error:
                refresh_error = str(error)

        # 1. Fetch existing API connections.
        connections = list(
            WearableConnection.objects.select_related("identity")
            .filter(
                customer_profile=customer_profile,
                connection_method=ConnectionMethod.API,
            )
            .order_by("data_source")
        )

        attach_connection_progress(connections, customer_profile)

        connection_details = [
            serialize_connection(connection)
            for connection in connections
        ]

        connections_by_source = {
            connection.data_source: connection
            for connection in connections
        }

        details_by_source = {
            detail["provider"]: detail
            for detail in connection_details
        }

        # 2. Fetch native connections separately.
        native_connections = list(
            WearableConnection.objects.select_related("identity")
            .filter(
                customer_profile=customer_profile,
                data_source__in=NATIVE_WEARABLE_SOURCES,
            )
            .order_by("data_source")
        )

        attach_connection_progress(
            native_connections,
            customer_profile,
        )

        native_connections_by_source = {
            connection.data_source: connection
            for connection in native_connections
        }

        # 3. Build native status entries, including never-connected sources.
        native_statuses = []

        for source in WearableSource.values:
            if source not in NATIVE_WEARABLE_SOURCES:
                continue

            connection = native_connections_by_source.get(source)

            native_statuses.append({
                "name": source,
                "connectionMethod": "native",
                "connected": (
                    connection is not None
                    and connection.authorization_status
                    == AuthorizationStatus.AUTHORIZED
                ),
                "status": (
                    connection.status
                    if connection
                    else ConnectionStatus.NEVER_CONNECTED
                ),
                "authorizationStatus": (
                    connection.authorization_status
                    if connection
                    else AuthorizationStatus.NOT_STARTED
                ),
                "permissionStatus": (
                    getattr(connection, "permission_status", None)
                    if connection
                    else None
                ),
                "connection": (
                    serialize_connection(connection)
                    if connection
                    else None
                ),
            })

        # 4. Fetch ROOK identity.
        identity = RookMemberIdentity.objects.filter(
            customer_profile=customer_profile
        ).first()

        # 5. Build API provider catalogue with connection statuses.
        provisioned = provisioned_sources()
        providers = []

        for source in WearableSource.values:
            if source in NATIVE_WEARABLE_SOURCES:
                continue

            # Strava's ROOK authorization route is unsupported.
            supported = source != WearableSource.STRAVA

            enabled = (
                supported
                and provisioned is not None
                and source in provisioned
            )

            connection = connections_by_source.get(source)

            authorized = (
                connection is not None
                and connection.authorization_status
                == AuthorizationStatus.AUTHORIZED
            )

            providers.append({
                "name": source,
                "connectionMethod": "api",
                "provisioned": (
                    enabled if provisioned is not None else None
                ),
                "selectable": enabled,
                "reason": (
                    "Provisioning not configured"
                    if provisioned is None
                    else "Unavailable"
                    if not enabled
                    else None
                ),
                "connected": authorized,
                "status": (
                    connection.status
                    if connection
                    else ConnectionStatus.NEVER_CONNECTED
                ),
                "authorizationStatus": (
                    connection.authorization_status
                    if connection
                    else AuthorizationStatus.NOT_STARTED
                ),
                # "connection": details_by_source.get(source),
            })

        # 6. Preserve existing combined response structure.
        data = {
            "providers": providers,
            "nativeStatuses": native_statuses,
            "provisioningConfigured": provisioned is not None,
            # "connections": connection_details,
            "connected": any(
                connection.authorization_status
                == AuthorizationStatus.AUTHORIZED
                and connection.data_source
                not in NATIVE_WEARABLE_SOURCES
                for connection in connections
            ),
            "rookUserId": (
                identity.rook_user_id
                if identity
                else None
            ),
            "refreshError": refresh_error,
        }

        return self.send_response(
            "ROOK provider availability retrieved.",
            data,
        )


class DeviceRetrySyncView(WearablesAPIView):
    """Retry a failed/delayed API import without rebuilding provider integrations."""
    serializer_class = DeviceDisconnectSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_connect"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def post(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        source = serializer.validated_data["data_source"]
        connection = WearableConnection.objects.filter(
            customer_profile=customer_profile, data_source=source
        ).first()
        if connection is None:
            raise NotFound("Device connection was not found.")
        if connection.status in {ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED}:
            self.raise_bad_request("Reconnect and reauthorize this provider before retrying synchronization.")
        if connection.authorization_status != AuthorizationStatus.AUTHORIZED:
            self.raise_bad_request("Wait for provider authorization before requesting sync.")
        if not has_active_wearable_consent(customer_profile):
            self.raise_bad_request("Wearable consent is required before requesting sync.")
        if connection.last_error_code == "provider_account_closed":
            self.raise_bad_request("This provider account is closed. Connect a different provider.")
        if connection.connection_method == ConnectionMethod.SDK:
            self.raise_bad_request("Re-run the ROOK native SDK sync on the member's device.")
        try:
            job, created = enqueue_or_reuse_fetch_rook_data_job(
                connection=connection, customer_profile=customer_profile, manual=True, flow="manual",
            )
        except ManualSyncCooldown as error:
            connection.refresh_from_db()
            return self.send_response(
                "Manual sync was requested recently. No additional job was queued.",
                {"jobId": str(error.job_id) if error.job_id else None, "queued": False,
                 "alreadyQueued": error.job_id is not None, "cooldownActive": True,
                 "syncRequestAccepted": False, "nextSyncAllowedAt": error.next_allowed_at,
                 "connection": serialize_connection(connection)}, status=200,
            )
        if job is None:
            self.raise_bad_request("Device connection changed. Refresh device status and retry.")
        if created:
            record_connection_event(
                connection,
                event_type="manual_sync_requested",
                previous_status=connection.status,
                actor_user=request.user,
                correlation_id=self.correlation_id(),
                detail="Member requested another ROOK API recovery attempt.",
            )
        connection.refresh_from_db()
        return self.send_response(
            "ROOK sync retry queued." if created else "ROOK sync is already queued.",
            {"jobId": str(job.pk), "queued": True, "alreadyQueued": not created,
             "cooldownActive": False, "syncRequestAccepted": True,
             "nextSyncAllowedAt": next_manual_sync_at(connection.last_manual_sync_queued_at),
             "connection": serialize_connection(connection)},
            status=202,
        )



class NativeDeviceStatusView(WearablesAPIView):
    serializer_class = NativeDeviceStatusSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def patch(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if not has_active_wearable_consent(customer_profile):
            self.raise_permission_denied(
                "Wearable consent has been revoked."
            )

        try:
            connection = update_native_connection(
                customer_profile=customer_profile,
                actor_user=request.user,
                validated_data=serializer.validated_data,
                correlation_id=self.correlation_id(),
            )
        except ValueError as error:
            self.raise_bad_request(str(error))

        return self.send_response(
            "Native wearable status updated.",
            {"connection": serialize_connection(connection)},
        )


class HealthDashboardView(WearablesAPIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "health_read"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        return self.send_response(
            "Health dashboard retrieved.",
            dashboard_payload(customer_profile),
        )


class HealthDomainView(WearablesAPIView):
    serializer_class = DomainQuerySerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "health_read"

    @extend_schema(
        parameters=[DomainQuerySerializer],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request, domain, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        if domain not in HEALTH_DOMAIN_ORDER:
            raise NotFound("Health domain not found.")
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        return self.send_response(
            "Health domain retrieved.",
            domain_payload(
                customer_profile=customer_profile,
                domain=domain,
                days=serializer.validated_data["days"],
                window=serializer.validated_data.get("window"),
            ),
        )

