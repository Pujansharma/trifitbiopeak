"""ROOK inbound webhook HTTP contract, using existing ingestion services/tables."""

import hashlib
import hmac
import json
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import Resolver404, resolve, reverse
from django.utils import timezone

from webhooks.rook.views import rook_data_webhook

CLIENT_UUID = "11111111-2222-4333-8444-555555555555"
SIGNING_KEY = "rook-test-signing-key-not-real"
TIMESTAMP = "2026-11-18T09:23:00.000000Z"


def data_payload(user_id="member-one", steps=7123):
    return {
        "client_uuid": CLIENT_UUID,
        "user_id": user_id,
        "version": 2,
        "data_structure": "physical_summary",
        "document_version": 1,
        "physical_health": {"summary": {"physical_summary": {
            "metadata": {"datetime_string": TIMESTAMP, "sources_of_data_array": ["Garmin"]},
            "distance": {"steps_int": steps},
        }}},
    }


def sign(payload):
    datetime_value = TIMESTAMP
    message = f"{payload['client_uuid']}{payload['user_id']}{datetime_value}"
    return hmac.new(SIGNING_KEY.encode(), message.encode(), hashlib.sha256).hexdigest()


@override_settings(ROOK_CLIENT_UUID=CLIENT_UUID, ROOK_WEBHOOK_HASH_KEY=SIGNING_KEY)
class RookWebhookHTTPTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def request(self, path, payload, *, hash_value=None, content_type="application/json"):
        return self.factory.post(
            path, data=json.dumps(payload), content_type=content_type,
            HTTP_X_ROOK_HASH=hash_value if hash_value is not None else sign(payload),
        )

    def test_routes_exist_and_are_post_only(self):
        self.assertEqual(resolve("/webhooks/rook/data/").func, rook_data_webhook)
        for url in ("/webhooks/rook/notification", "/webhooks/rook/notification/"):
            with self.subTest(url=url), self.assertRaises(Resolver404):
                resolve(url)
        self.assertEqual(reverse("rook-data-webhook"), "/webhooks/rook/data/")
        self.assertEqual(rook_data_webhook(self.factory.get("/webhooks/rook/data/")).status_code, 405)

    @patch("webhooks.rook.views.ingest_rook_document", return_value={"accepted": True, "processed": True})
    def test_valid_data_delivery_is_processed(self, service):
        payload = data_payload()
        response = rook_data_webhook(self.request("/webhooks/rook/data/", payload))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["processed"], True)
        service.assert_called_once_with(payload, signature_valid=True)

    @patch("webhooks.rook.views.ingest_rook_document")
    def test_bad_signature_is_rejected_without_storage(self, service):
        response = rook_data_webhook(self.request(
            "/webhooks/rook/data/", data_payload(), hash_value="bad-signature",
        ))
        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    @patch("webhooks.rook.views.ingest_rook_document")
    def test_wrong_client_is_rejected(self, service):
        payload = data_payload()
        payload["client_uuid"] = "different-client"
        response = rook_data_webhook(self.request("/webhooks/rook/data/", payload))
        self.assertEqual(response.status_code, 403)
        service.assert_not_called()

    @override_settings(ROOK_WEBHOOK_HASH_KEY="", ROOK_ALLOW_UNSIGNED_WEBHOOKS=True)
    @patch("webhooks.rook.views.ingest_rook_document")
    def test_missing_key_fails_closed_even_with_legacy_flag(self, service):
        response = rook_data_webhook(self.request("/webhooks/rook/data/", data_payload()))
        self.assertEqual(response.status_code, 503)
        service.assert_not_called()

    @patch("webhooks.rook.views.ingest_rook_document")
    def test_invalid_json_is_rejected(self, service):
        request = self.factory.post(
            "/webhooks/rook/data/", data="{not json", content_type="application/json"
        )
        self.assertEqual(rook_data_webhook(request).status_code, 400)
        service.assert_not_called()

    @patch("webhooks.rook.views.ingest_rook_document", side_effect=RuntimeError("failed"))
    def test_processing_failure_returns_retryable_503(self, service):
        response = rook_data_webhook(self.request("/webhooks/rook/data/", data_payload()))
        self.assertEqual(response.status_code, 503)
        service.assert_called_once()

    @patch("webhooks.rook.views.ingest_rook_document", return_value={"accepted": True, "duplicate": True})
    def test_duplicate_is_acknowledged_without_raw_health_data(self, service):
        response = rook_data_webhook(self.request("/webhooks/rook/data/", data_payload()))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content), {"accepted": True, "duplicate": True})



@override_settings(ROOK_CLIENT_UUID=CLIENT_UUID, ROOK_WEBHOOK_HASH_KEY=SIGNING_KEY)
class RookWebhookPersistedDataTests(TestCase):
    """Exercise actual transaction/normalization rather than only mocking the view."""

    def setUp(self):
        from accounts.customers.models import Customer, CustomerProfile
        from accounts.models import UserAccount
        from accounts.users.models import User
        from accounts.utils.constants import UserType
        from wearables.models import WearableConsent
        from wearables.services.connections import get_or_create_connection
        from wearables.services.identity import get_or_create_rook_identity
        from wearables.utils.constants import (
            AuthorizationStatus, ConnectionStatus, ConsentStatus, PermissionStatus,
        )

        user = User.objects.create_user(email="rook-webhook@example.com")
        UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=user)
        profile = CustomerProfile.objects.create(
            customer=customer, first_name="Webhook", last_name="Test", is_main=True,
        )
        self.identity = get_or_create_rook_identity(profile)
        WearableConsent.objects.create(
            customer_profile=profile, granted_by=user,
            status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now(),
        )
        connection = get_or_create_connection(
            customer_profile=profile, identity=self.identity,
            data_source="Garmin", historical_days_requested=7,
        )
        connection.status = ConnectionStatus.ACTIVE
        connection.authorization_status = AuthorizationStatus.AUTHORIZED
        connection.permission_status = PermissionStatus.GRANTED
        connection.save()

    def test_signed_data_creates_summary_and_duplicate_is_idempotent(self):
        from wearables.models import HealthDailySummary, RookWebhookReceipt

        payload = data_payload(user_id=self.identity.rook_user_id)
        request_factory = RequestFactory()
        def deliver():
            request = request_factory.post(
                "/webhooks/rook/data/", data=json.dumps(payload),
                content_type="application/json", HTTP_X_ROOK_HASH=sign(payload),
            )
            with self.captureOnCommitCallbacks(execute=True):
                return rook_data_webhook(request)
        first = deliver()
        self.assertEqual(first.status_code, 200)
        self.assertEqual(HealthDailySummary.objects.get(metric="steps").maximum, 7123.0)
        self.assertEqual(RookWebhookReceipt.objects.filter(status="processed").count(), 1)
        second = deliver()
        self.assertEqual(second.status_code, 200)
        self.assertTrue(json.loads(second.content).get("duplicate"))
        self.assertEqual(HealthDailySummary.objects.filter(metric="steps").count(), 1)
