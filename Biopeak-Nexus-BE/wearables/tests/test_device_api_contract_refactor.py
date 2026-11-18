"""ROOK client API contract checks after removing the legacy state callback.

Run: uv run python manage.py test wearables.tests.test_device_api_contract_refactor -v 2
No database and no live ROOK account are required for these focused tests.
"""
from types import SimpleNamespace
from urllib.parse import urlsplit
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import Resolver404, resolve
from rest_framework.test import APIRequestFactory

from wearables.utils.constants import (
    AuthorizationStatus,
    ConnectionStatus,
    NATIVE_WEARABLE_SOURCES,
    WearableSource,
)
from wearables.services.client import RookConfigurationError
from wearables.views import (
    DeviceConnectView,
    DeviceDisconnectView,
    DeviceProviderCatalogueView,
    DeviceRetrySyncView,
    HealthDashboardView,
    HealthDomainView,
    NativeDeviceStatusView,
)


class RookClientRouteTests(SimpleTestCase):
    def test_supported_device_routes_resolve_to_the_intended_views(self):
        cases = {
            "/api/v1/devices/connect/": DeviceConnectView,
            "/api/v1/devices/disconnect/": DeviceDisconnectView,
            "/api/v1/devices/providers/": DeviceProviderCatalogueView,
            "/api/v1/devices/sync/": DeviceRetrySyncView,
            "/api/v1/devices/native-status/": NativeDeviceStatusView,
        }
        for url, expected_view in cases.items():
            with self.subTest(url=url):
                self.assertIs(resolve(url).func.view_class, expected_view)

    def test_providers_refresh_query_parameter_uses_the_same_route(self):
        self.assertIs(
            resolve(urlsplit("/api/v1/devices/providers/?refresh=true").path).func.view_class,
            DeviceProviderCatalogueView,
        )

    def test_mobile_oauth_return_and_renamed_health_routes(self):
        self.assertEqual(resolve("/rook/return/").url_name, "rook-oauth-mobile-return-slash")
        self.assertIs(resolve("/api/v1/health/domain-summary/").func.view_class, HealthDashboardView)
        self.assertIs(resolve("/api/v1/health/domain-summary/heart/").func.view_class, HealthDomainView)
        for url in (
            "/api/v1/health/dashboard/",
            "/api/v1/health/heart/",
            "/api/v1/health/timeline/",
        ):
            with self.subTest(url=url), self.assertRaises(Resolver404):
                resolve(url)

    def test_retired_device_and_state_routes_are_not_resolvable(self):
        removed = (
            "/api/v1/devices/",
            "/api/v1/devices/retry-sync/",
            "/api/v1/devices/consent/revoke/",
            "/api/v1/devices/sdk-config/",
            "/webhooks/rook/data/",
            "/webhooks/rook/notification/",
            "/r/AAAAAAAAAAAAAAAA/client_uuid/f2f2e6d2-1467-4ecc-bb4d-9bfc1249458e/user_id/example",
            "/r/AAAAAAAAAAAAAAAA/client_uuid/f2f2e6d2-1467-4ecc-bb4d-9bfc1249458e/user_id/example/",
        )
        for url in removed:
            with self.subTest(url=url), self.assertRaises(Resolver404):
                resolve(url)

    def test_native_status_rejects_post_but_accepts_patch_handler(self):
        class NativeNoAuthView(NativeDeviceStatusView):
            authentication_classes = ()
            permission_classes = ()
            throttle_classes = ()

        request = APIRequestFactory().post("/api/v1/devices/native-status/", {}, format="json")
        result = NativeNoAuthView.as_view()(request)
        self.assertEqual(result.status_code, 405)
        self.assertTrue(callable(NativeDeviceStatusView.patch))
        self.assertFalse(hasattr(NativeDeviceStatusView, "post"))
        self.assertTrue(callable(DeviceRetrySyncView.post))
        self.assertTrue(callable(DeviceConnectView.post))
        self.assertTrue(callable(DeviceDisconnectView.post))


class RookCombinedProviderContractTests(SimpleTestCase):
    def provider_data(self, *, refresh=False, error=None):
        profile = object()
        api_connections = [
            SimpleNamespace(data_source="Garmin", status=ConnectionStatus.ACTIVE,
                            authorization_status=AuthorizationStatus.AUTHORIZED),
            SimpleNamespace(data_source="Fitbit", status=ConnectionStatus.AUTHORIZING,
                            authorization_status=AuthorizationStatus.PENDING),
        ]
        native_source = next(iter(sorted(NATIVE_WEARABLE_SOURCES)))
        native_connections = [
            SimpleNamespace(data_source=native_source, status=ConnectionStatus.ACTIVE,
                            authorization_status=AuthorizationStatus.AUTHORIZED,
                            permission_status="granted"),
        ]
        view = DeviceProviderCatalogueView()
        view.get_customer_profile = MagicMock(return_value=profile)
        view.send_response = MagicMock(side_effect=lambda _detail, payload: payload)
        request = SimpleNamespace(query_params={"refresh": "true"} if refresh else {})

        with (
            patch("wearables.views.WearableConnection.objects.select_related") as select_related,
            patch("wearables.views.RookMemberIdentity.objects.filter") as identities,
            patch("wearables.views.attach_connection_progress") as progress,
            patch("wearables.views.serialize_connection") as serialize,
            patch("wearables.views.provisioned_sources", return_value={"Garmin", "Fitbit"}),
            patch("wearables.views.refresh_authorizing_connections") as refresh_authorizations,
        ):
            select_related.return_value.filter.return_value.order_by.side_effect = [
                api_connections, native_connections,
            ]
            identities.return_value.first.return_value = SimpleNamespace(rook_user_id="rook-member-1")
            serialize.side_effect = lambda connection: {
                "provider": connection.data_source,
                "status": connection.status,
                "authorizationStatus": connection.authorization_status,
            }
            if error is not None:
                refresh_authorizations.side_effect = RookConfigurationError(error)
            data = view.get(request)
            self.assertEqual(progress.call_count, 2)
            if refresh:
                refresh_authorizations.assert_called_once_with(profile)
            else:
                refresh_authorizations.assert_not_called()
            return data, native_source

    def test_combined_catalogue_shows_all_providers_and_only_two_api_connections(self):
        data, native_source = self.provider_data()
        api_sources = set(WearableSource.values) - set(NATIVE_WEARABLE_SOURCES)
        self.assertEqual({provider["name"] for provider in data["providers"]}, api_sources)
        self.assertEqual(len(data["connections"]), 2)
        self.assertEqual({record["name"] for record in data["nativeStatuses"]}, set(NATIVE_WEARABLE_SOURCES))
        by_source = {entry["name"]: entry for entry in data["providers"]}
        self.assertTrue(by_source["Garmin"]["connected"])
        self.assertEqual(by_source["Garmin"]["status"], ConnectionStatus.ACTIVE)
        self.assertFalse(by_source["Fitbit"]["connected"])
        self.assertEqual(by_source["Fitbit"]["status"], ConnectionStatus.AUTHORIZING)
        untouched = next(source for source in api_sources if source not in {"Garmin", "Fitbit"})
        self.assertEqual(by_source[untouched]["status"], ConnectionStatus.NEVER_CONNECTED)
        native_by_source = {entry["name"]: entry for entry in data["nativeStatuses"]}
        self.assertEqual(native_by_source[native_source]["permissionStatus"], "granted")
        self.assertIsNotNone(native_by_source[native_source]["connection"])
        self.assertIsNone(data["refreshError"])
        self.assertEqual(data["rookUserId"], "rook-member-1")
        self.assertTrue(data["connected"])

    def test_refresh_true_retains_same_payload_and_verifies_pending_authorization(self):
        original, _ = self.provider_data()
        updated, _ = self.provider_data(refresh=True)
        self.assertEqual(set(original), set(updated))
        self.assertEqual(set(original["providers"][0]), set(updated["providers"][0]))
        self.assertIsNone(updated["refreshError"])

    def test_refresh_error_is_reported_without_hiding_saved_provider_statuses(self):
        updated, _ = self.provider_data(refresh=True, error="temporarily unavailable")
        self.assertEqual(updated["refreshError"], "temporarily unavailable")
        self.assertEqual(len(updated["connections"]), 2)
        self.assertEqual(len(updated["nativeStatuses"]), len(NATIVE_WEARABLE_SOURCES))
