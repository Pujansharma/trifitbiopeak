"""Reviewer P1: mobile SDK config contract and credential separation.

Run with Python 3.14 and the project's Django dependencies:
uv run python manage.py test wearables.tests.test_pr143_sdk_config_contract
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.exceptions import ParseError, PermissionDenied

from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.views import DeviceSDKConfigView
from accounts.customers.models import Customer, CustomerProfile
from accounts.users.models import User
from wearables.models import WearableConsent, WearableConnection
from wearables.services.connections import get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.utils.constants import (
    ConnectionStatus, ConsentStatus, NATIVE_WEARABLE_SOURCES,
)


class SDKConfigReviewerContractTests(SimpleTestCase):
    def get_sdk_config(self, *, consent=True, connection=True):
        profile = SimpleNamespace(pk="test-profile")
        native = SimpleNamespace(identity=SimpleNamespace(rook_user_id="bp-test-member")) if connection else None
        with (
            patch.object(DeviceSDKConfigView, "get_customer_profile", return_value=profile),
            patch("wearables.views.WearableConnection.objects.select_related") as related,
            patch("wearables.views.has_active_wearable_consent", return_value=consent),
        ):
            related.return_value.filter.return_value.exclude.return_value.first.return_value = native
            response = DeviceSDKConfigView().get(SimpleNamespace())
            filter_kwargs = related.return_value.filter.call_args.kwargs
        return response, filter_kwargs

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health,Garmin",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
        ROOK_ENVIRONMENT="sandbox",
    )
    def test_exact_success_payload_and_no_store_cache_header(self):
        response, constraints = self.get_sdk_config()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, {
            "detail": "ROOK mobile SDK configuration retrieved.",
            "data": {
                "clientUuid": "sdk-client-uuid",
                "secret": "sdk-secret-word-test",
                "environment": "sandbox",
                "rookUserId": "bp-test-member",
            },
        })
        self.assertNotIn("server-api-key-test", str(response.data))
        self.assertEqual(response["Cache-Control"], "no-store, private")
        self.assertEqual(constraints["data_source__in"], {"Apple Health"})
        self.assertEqual(constraints["data_source__in"], NATIVE_WEARABLE_SOURCES & {"Apple Health", "Garmin"})

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Garmin",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_unprovisioned_native_source_is_not_eligible_for_config(self):
        _, constraints = self.get_sdk_config()
        self.assertFalse(constraints["data_source__in"])

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_no_active_consent_blocks_client_credential(self):
        with self.assertRaises(PermissionDenied):
            self.get_sdk_config(consent=False)

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_no_native_connection_blocks_client_credential(self):
        with self.assertRaises(ParseError):
            self.get_sdk_config(connection=False)

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=False,
    )
    def test_distribution_disabled_returns_503_without_secret(self):
        response, _ = self.get_sdk_config()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("sdk-secret-word-test", str(response.data))

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_SDK_SECRET="server-api-key-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_server_api_secret_can_never_be_returned(self):
        response, _ = self.get_sdk_config()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("server-api-key-test", str(response.data))

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="sdk-client-uuid",
        ROOK_CLIENT_UUID="different-api-client-uuid",
        ROOK_SDK_SECRET="sdk-secret-word-test",
        ROOK_SECRET_KEY="server-api-key-test",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
    )
    def test_sdk_and_api_different_client_uuid_report_deployment_error(self):
        checks = rook_readiness_checks()
        self.assertTrue(any(
            severity == "ERROR" and field == "ROOK_SDK_CLIENT_UUID"
            for severity, field, _ in checks
        ))


class SDKConfigDatabaseEligibilityTests(TestCase):
    """Use the real ORM: mock queryset chains can conceal eligibility bugs."""

    def setUp(self):
        user = User.objects.create_user(email="pr143-sdk-config@example.com")
        customer = Customer.objects.create(user=user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="SDK", last_name="Review", is_main=True,
        )
        identity = get_or_create_rook_identity(self.profile)
        connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity,
            data_source="Apple Health", historical_days_requested=0,
        )
        WearableConnection.objects.filter(pk=connection.pk).update(
            status=ConnectionStatus.CONNECTING,
        )
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=user,
            status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now(),
        )

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Garmin",
        ROOK_SDK_CLIENT_UUID="same-rook-client",
        ROOK_SDK_SECRET="test-sdk-word",
        ROOK_SECRET_KEY="test-api-secret",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
        ROOK_ENVIRONMENT="sandbox",
    )
    def test_removed_native_provider_cannot_retrieve_mobile_credential(self):
        with patch.object(DeviceSDKConfigView, "get_customer_profile", return_value=self.profile):
            with self.assertRaises(ParseError):
                DeviceSDKConfigView().get(SimpleNamespace())

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health",
        ROOK_SDK_CLIENT_UUID="same-rook-client",
        ROOK_SDK_SECRET="test-sdk-word",
        ROOK_SECRET_KEY="test-api-secret",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True,
        ROOK_ENVIRONMENT="sandbox",
    )
    def test_provisioned_native_provider_can_retrieve_expected_identity(self):
        with patch.object(DeviceSDKConfigView, "get_customer_profile", return_value=self.profile):
            response = DeviceSDKConfigView().get(SimpleNamespace())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"]["secret"], "test-sdk-word")
        self.assertEqual(response.data["data"]["rookUserId"], self.profile.rook_identity.rook_user_id)
