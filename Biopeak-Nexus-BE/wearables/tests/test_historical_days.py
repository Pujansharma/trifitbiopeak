"""Regression tests for PRD 7/29-day ROOK connection windows.

Run when the project's Django environment is available:
    uv run python manage.py test wearables.tests.test_historical_days
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from wearables.serializers import DeviceConnectSerializer
from wearables.views import DeviceConnectView


@override_settings(ROOK_ENVIRONMENT="sandbox", ROOK_PREEXISTING_ENABLED=True)
class HistoricalDaysSerializerTests(SimpleTestCase):
    @staticmethod
    def payload(source="Garmin", days=29):
        return {
            "data_source": source,
            "consent_accepted": True,
            "consent_version": "v1",
            "historical_days": days,
            "timezone_name": "Asia/Kolkata",
            "preferred_units": "metric",
        }

    def test_garmin_29_day_request_is_accepted_with_only_seven_applied(self):
        serializer = DeviceConnectSerializer(data=self.payload())
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.requested_historical_days, 29)
        self.assertEqual(serializer.max_historical_days, 7)
        self.assertEqual(serializer.validated_data["historical_days"], 7)

    def test_other_api_provider_29_day_request_is_limited_to_seven(self):
        for provider in ("Fitbit", "Oura", "Polar", "Whoop", "Withings", "Dexcom"):
            with self.subTest(provider=provider):
                serializer = DeviceConnectSerializer(data=self.payload(provider))
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["historical_days"], 7)

    def test_native_sdk_sources_can_request_29_days(self):
        for provider in ("Apple Health", "Health Connect", "Samsung Health"):
            with self.subTest(provider=provider):
                serializer = DeviceConnectSerializer(data=self.payload(provider))
                self.assertTrue(serializer.is_valid(), serializer.errors)
                self.assertEqual(serializer.validated_data["historical_days"], 29)
                self.assertEqual(serializer.max_historical_days, 29)

    @override_settings(ROOK_HISTORICAL_DAYS=29)
    def test_garmin_without_explicit_window_defaults_to_seven(self):
        payload = self.payload()
        payload.pop("historical_days")
        serializer = DeviceConnectSerializer(data=payload)
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 7)
        self.assertEqual(serializer.requested_historical_days, 7)

    def test_valid_five_day_request_is_not_expanded(self):
        serializer = DeviceConnectSerializer(data=self.payload(days=5))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 5)

    def test_zero_disables_preexisting_import(self):
        serializer = DeviceConnectSerializer(data=self.payload(days=0))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 0)

    def test_invalid_values_still_rejected(self):
        for days in (-1, 30, "not-an-integer"):
            with self.subTest(days=days):
                serializer = DeviceConnectSerializer(data=self.payload(days=days))
                self.assertFalse(serializer.is_valid())
                self.assertIn("historical_days", serializer.errors)

    def test_missing_consent_still_rejected(self):
        payload = self.payload()
        payload["consent_accepted"] = False
        serializer = DeviceConnectSerializer(data=payload)
        self.assertFalse(serializer.is_valid())
        self.assertIn("consent_accepted", serializer.errors)


@override_settings(ROOK_ENVIRONMENT="sandbox", ROOK_PREEXISTING_ENABLED=True)
class HistoricalDaysConnectResponseTests(SimpleTestCase):
    @patch("wearables.views.start_connection")
    @patch("wearables.views.serialize_connection")
    def test_garmin_29_day_payload_is_passed_as_seven_and_disclosed(self, serialize, start):
        serialize.return_value = {"historicalDaysRequested": 7}
        start.return_value = {
            "connection": SimpleNamespace(identity=SimpleNamespace(rook_user_id="test-rook-user")),
            "authorization_method": "api",
            "authorization_url": "https://connect.garmin.com/authorize",
        }
        view = DeviceConnectView()
        view.get_customer_profile = lambda: object()
        view.get_serializer = lambda *, data: DeviceConnectSerializer(data=data)
        view.correlation_id = lambda: "correlation-test"
        request = SimpleNamespace(data=HistoricalDaysSerializerTests.payload(), user=object())

        response = view.post(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(start.call_args.kwargs["validated_data"]["historical_days"], 7)
        self.assertEqual(response.data["data"]["connection"]["historicalDaysRequested"], 7)
        history = response.data["data"]["historicalImport"]
        self.assertEqual(history["requestedDays"], 29)
        self.assertEqual(history["appliedDays"], 7)
        self.assertEqual(history["maxSupportedDays"], 7)
        self.assertTrue(history["adjusted"])
        self.assertIn("Garmin", history["notice"])

    @patch("wearables.views.start_connection")
    @patch("wearables.views.serialize_connection", return_value={"historicalDaysRequested": 7})
    def test_garmin_valid_request_reports_no_adjustment(self, serialize, start):
        start.return_value = {
            "connection": SimpleNamespace(identity=SimpleNamespace(rook_user_id="test-rook-user")),
            "authorization_method": "api", "authorization_url": None,
        }
        view = DeviceConnectView()
        view.get_customer_profile = lambda: object()
        view.get_serializer = lambda *, data: DeviceConnectSerializer(data=data)
        view.correlation_id = lambda: "correlation-test"
        request = SimpleNamespace(data=HistoricalDaysSerializerTests.payload(days=7), user=object())

        response = view.post(request)

        self.assertEqual(response.status_code, 201)
        history = response.data["data"]["historicalImport"]
        self.assertEqual(history["requestedDays"], 7)
        self.assertEqual(history["appliedDays"], 7)
        self.assertFalse(history["adjusted"])
        self.assertNotIn("notice", history)


class HistoricalDaysProductionPolicyTests(SimpleTestCase):
    @override_settings(ROOK_ENVIRONMENT="production", ROOK_PREEXISTING_ENABLED=False)
    def test_production_preexisting_import_is_off_without_explicit_opt_in(self):
        serializer = DeviceConnectSerializer(data=HistoricalDaysSerializerTests.payload(days=29))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 0)
        self.assertTrue(serializer.history_disabled_by_policy)

    @override_settings(ROOK_ENVIRONMENT="production", ROOK_PREEXISTING_ENABLED=True)
    def test_operator_may_enable_bounded_7_day_rook_import(self):
        serializer = DeviceConnectSerializer(data=HistoricalDaysSerializerTests.payload(days=29))
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 7)

    @override_settings(ROOK_PROVISIONED_SOURCES=["Fitbit"])
    def test_non_provisioned_provider_does_not_get_connect_url(self):
        serializer = DeviceConnectSerializer(data=HistoricalDaysSerializerTests.payload(days=7))
        self.assertFalse(serializer.is_valid())
        self.assertIn("data_source", serializer.errors)
