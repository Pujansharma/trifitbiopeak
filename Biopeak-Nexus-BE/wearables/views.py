from django.http import JsonResponse
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView
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
    TimelineQuerySerializer,
)
from wearables.services.analytics import (
    dashboard_payload,
    domain_payload,
    timeline_payload,
)
from wearables.services.client import RookConfigurationError, RookServiceError
from wearables.services.connections import (
    disconnect_connection,
    record_connection_event,
    refresh_authorizing_connections,
    serialize_connection,
    start_connection,
    update_native_connection,
)
from wearables.services.identity import resolve_customer_profile
from wearables.services.oauth import complete_oauth_callback, OAuthStateError
from wearables.services.consent import has_active_wearable_consent, revoke_wearable_consent
from wearables.services.job_queue import enqueue_health_job
from wearables.utils.constants import (HEALTH_DOMAIN_ORDER, ConnectionMethod, ConnectionStatus,
    HealthJobType, HistoricalImportStatus, WearableSource, NATIVE_WEARABLE_SOURCES)


class WearablesAPIView(BaseGenericAPIView):
    permission_classes = (IsCustomerUser,)

    def ensure_wearables_enabled(self) -> None:
        if not getattr(settings, "WEARABLES_ENABLED", True):
            raise NotFound("Wearable integration is not enabled.")

    def ensure_profile_feature_enabled(self, customer_profile) -> None:
        if not getattr(settings, "WEARABLES_REQUIRE_PROFILE_FEATURE", False):
            return
        feature = getattr(customer_profile, "feature", None)
        if feature is None or FeatureTabOptions.WEARABLES not in feature.enabled_tabs:
            raise NotFound("Wearable integration is not enabled for this profile.")

    def get_customer_profile(self):
        self.ensure_wearables_enabled()
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


class DeviceListView(WearablesAPIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        refresh_requested = request.query_params.get("refresh", "").lower() in {
            "1",
            "true",
        }
        refresh_error = None
        if refresh_requested:
            try:
                refresh_authorizing_connections(customer_profile)
            except (RookConfigurationError, RookServiceError) as error:
                refresh_error = str(error)
        connections = list(
            WearableConnection.objects.select_related("identity")
            .filter(customer_profile=customer_profile)
            .order_by("data_source")
        )
        identity = RookMemberIdentity.objects.filter(
            customer_profile=customer_profile
        ).first()
        data = {
            "connections": [
                serialize_connection(connection) for connection in connections
            ],
            "connected": any(
                connection.authorization_status == "authorized"
                for connection in connections
            ),
            "rookUserId": identity.rook_user_id if identity else None,
            "refreshError": refresh_error,
        }
        return self.send_response("Connected devices retrieved.", data)


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
    """Expose explicit provider provisioning, so mobile hides disabled choices."""
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, *args, **kwargs):
        self.get_customer_profile()
        from wearables.services.config import provisioned_sources
        provisioned = provisioned_sources()
        providers = []
        for source in WearableSource.values:
            is_native = source in NATIVE_WEARABLE_SOURCES
            # Strava's current ROOK authorizer route is unsupported here.
            supported = source != WearableSource.STRAVA
            enabled = supported and (provisioned is not None and source in provisioned)
            providers.append({
                "name": source,
                "connectionMethod": "sdk" if is_native else "api",
                "provisioned": (enabled if provisioned is not None else None),
                "selectable": enabled,
                "reason": ("Provisioning not configured" if provisioned is None
                           else "Unavailable" if not enabled else None),
            })
        return self.send_response(
            "ROOK provider availability retrieved.",
            {"providers": providers, "provisioningConfigured": provisioned is not None},
        )


class DeviceSDKConfigView(WearablesAPIView):
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        native_connection = (
            WearableConnection.objects.select_related("identity")
            .filter(
                customer_profile=customer_profile,
                connection_method=ConnectionMethod.SDK,
            )
            .first()
        )
        if native_connection is None:
            self.raise_bad_request(
                "Start a native wearable connection before requesting SDK configuration."
            )
        if not has_active_wearable_consent(customer_profile):
            self.raise_permission_denied("Wearable consent must be granted before using the SDK.")
        identity = native_connection.identity
        client_uuid = getattr(settings, "ROOK_SDK_CLIENT_UUID", "")
        sdk_secret = getattr(settings, "ROOK_SDK_SECRET", "")
        if not client_uuid or not sdk_secret:
            return self.send_response("ROOK mobile SDK is not configured.", status=503)
        data = {
            "clientUuid": client_uuid,
            "secret": sdk_secret,
            "environment": getattr(settings, "ROOK_ENVIRONMENT", "sandbox"),
            "rookUserId": identity.rook_user_id,
        }
        return self.send_response("ROOK mobile SDK configuration retrieved.", data)


class NativeDeviceStatusView(WearablesAPIView):
    serializer_class = NativeDeviceStatusSerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_status"

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def post(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        if not has_active_wearable_consent(customer_profile):
            self.raise_permission_denied("Wearable consent has been revoked.")
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


class HealthTimelineView(WearablesAPIView):
    serializer_class = TimelineQuerySerializer
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "health_read"

    @extend_schema(
        parameters=[TimelineQuerySerializer],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request, *args, **kwargs):
        if not getattr(settings, "TIMELINE_ENABLED", True):
            raise NotFound("Health timeline is not enabled.")
        customer_profile = self.get_customer_profile()
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        data = timeline_payload(
            customer_profile=customer_profile,
            start_date=serializer.validated_data.get("start"),
            end_date=serializer.validated_data.get("end"),
            domain=serializer.validated_data.get("domain"),
            offset=serializer.validated_data["offset"],
            limit=serializer.validated_data["limit"],
        )
        return self.send_response("Health timeline retrieved.", data)



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
        if connection.last_error_code == "provider_account_closed":
            self.raise_bad_request("This provider account is closed. Connect a different provider.")
        if connection.connection_method == ConnectionMethod.SDK:
            self.raise_bad_request("Re-run the ROOK native SDK sync on the member's device.")
        connection.import_status = HistoricalImportStatus.RUNNING
        connection.save(update_fields=["import_status", "updated_at"])
        job = enqueue_health_job(
            job_type=HealthJobType.RECOVERY_PULL,
            idempotency_key=f"manual-recovery:{connection.pk}:{uuid.uuid4()}",
            customer_profile=customer_profile,
            connection=connection,
        )
        record_connection_event(
            connection,
            event_type="manual_sync_requested",
            previous_status=connection.status,
            actor_user=request.user,
            correlation_id=self.correlation_id(),
            detail="Member requested another ROOK API recovery attempt.",
        )
        return self.send_response(
            "ROOK sync retry queued.",
            {"jobId": str(job.pk), "queued": True, "connection": serialize_connection(connection)},
            status=202,
        )


class RookOAuthCallbackView(APIView):
    """Public ROOK browser return. Never trusts callback parameters as authorization."""
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def get(self, request, *args, **kwargs):
        state_token = kwargs.get("state_token", "")
        client_uuid = kwargs.get("client_uuid", "")
        rook_user_id = kwargs.get("rook_user_id", "")
        cancelled = bool(request.query_params.get("error")) or request.query_params.get("cancelled", "").lower() in ("1", "true", "yes")
        try:
            outcome = complete_oauth_callback(
                state_token, rook_client_uuid=client_uuid, rook_user_id=rook_user_id, cancelled=cancelled
            )
        except OAuthStateError:
            return JsonResponse({"detail": "Authorization state is invalid or already used."}, status=400)
        except (RookConfigurationError, RookServiceError):
            return JsonResponse({"detail": "ROOK authorization confirmation is temporarily unavailable. Check device status in the app."}, status=503)
        if outcome == "authorized":
            return JsonResponse({"detail": "Authorization confirmed. Return to the Biopeak app."})
        if outcome in ("cancelled", "expired"):
            return JsonResponse({"detail": "Authorization was not completed. Retry from the Biopeak app."}, status=410)
        return JsonResponse({"detail": "Authorization is being confirmed. Return to the Biopeak app and refresh device status."}, status=202)


class DeviceConsentRevokeView(WearablesAPIView):
    """Member-initiated opt-out; no source or account data is deleted."""
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "wearable_connect"

    @extend_schema(responses={200: OpenApiTypes.OBJECT})
    def post(self, request, *args, **kwargs):
        # Privacy opt-out remains accessible even after feature rollout is disabled.
        customer_profile = resolve_customer_profile(request)
        data = revoke_wearable_consent(
            customer_profile=customer_profile,
            actor_user=request.user,
            correlation_id=self.correlation_id(),
        )
        return self.send_response("Wearable consent revoked. Existing health history retained.", data)
