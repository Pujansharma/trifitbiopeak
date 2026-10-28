"""Focused follow-up tests for three older reviewer comments.

Run under the application's Python 3.14 and Django/PostgreSQL environment:
uv run python manage.py test wearables.tests.test_older_pr143_security_cache_remap

ROOK Portal validation and edge rate limiting require separate deployment checks.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import caches
from django.core.cache.backends.dummy import DummyCache
from django.test import SimpleTestCase, override_settings

from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.services.analytics import dashboard_payload, shared_health_cache_enabled
from wearables.utils.constants import ConnectionStatus
from wearables.views import DeviceSDKConfigView


TEST_CACHE_SETTINGS = {
    "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    "health": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
}


class OlderPR143SecurityAndCacheTests(SimpleTestCase):
    def sdk_response(self):
        connection = SimpleNamespace(identity=SimpleNamespace(rook_user_id="rook-test-member"))
        profile = SimpleNamespace(pk="test-profile")
        with (
            patch.object(DeviceSDKConfigView, "get_customer_profile", return_value=profile),
            patch("wearables.views.WearableConnection.objects.select_related") as select_related,
            patch("wearables.views.has_active_wearable_consent", return_value=True),
        ):
            select_related.return_value.filter.return_value.exclude.return_value.first.return_value = connection
            response = DeviceSDKConfigView().get(SimpleNamespace())
            excluded_statuses = select_related.return_value.filter.return_value.exclude.call_args.kwargs["status__in"]
        return response, excluded_statuses

    @override_settings(
        ROOK_SDK_CLIENT_UUID="native-client", ROOK_SDK_SECRET="native-only-test-secret",
        ROOK_SECRET_KEY="server-private-test-secret",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=False,
    )
    def test_sdk_secret_not_returned_without_explicit_approval(self):
        response, _ = self.sdk_response()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("native-only-test-secret", str(response.data))

    @override_settings(
        ROOK_SDK_CLIENT_UUID="native-client", ROOK_SDK_SECRET="same-key",
        ROOK_SECRET_KEY="same-key", ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_sdk_server_basic_auth_key_is_never_returned(self):
        response, _ = self.sdk_response()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("same-key", str(response.data))

    @override_settings(
        ROOK_SDK_CLIENT_UUID="native-client", ROOK_SDK_SECRET="mobile-test-secret",
        ROOK_SECRET_KEY="server-private-test-secret",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
        ROOK_ENVIRONMENT="sandbox",
    )
    def test_only_approved_distinct_mobile_credential_is_distributable(self):
        response, excluded_statuses = self.sdk_response()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["secret"], "mobile-test-secret")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertCountEqual(excluded_statuses, [
            ConnectionStatus.NEVER_CONNECTED,
            ConnectionStatus.DISCONNECTED,
            ConnectionStatus.AUTHORIZATION_EXPIRED,
            ConnectionStatus.PERMISSION_DENIED,
        ])

    @override_settings(CACHES=TEST_CACHE_SETTINGS)
    def test_health_cache_disabled_and_reads_from_database_snapshots(self):
        self.assertIsInstance(caches["health"], DummyCache)
        self.assertFalse(shared_health_cache_enabled())
        profile = SimpleNamespace(pk="cache-test-profile")
        with (
            patch("wearables.services.analytics.HealthDomainSnapshot.objects.filter", return_value=[]),
            patch("wearables.services.analytics.refresh_profile_snapshots", return_value=[{"domain": "heart"}]) as refresh,
        ):
            payload = dashboard_payload(profile)
        self.assertEqual(payload["cards"], [{"domain": "heart"}])
        refresh.assert_called_once_with(profile)

    @override_settings(WEARABLES_ENABLED=True, CACHES=TEST_CACHE_SETTINGS)
    def test_local_memory_throttling_is_reported_as_deployment_warning(self):
        findings = rook_readiness_checks()
        self.assertTrue(any(
            severity == "WARN" and key == "WEARABLE_EDGE_RATE_LIMIT"
            for severity, key, _ in findings
        ))
