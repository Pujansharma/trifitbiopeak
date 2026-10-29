"""Regression coverage for PR #143's fail-closed authorizer and reconnects.

Run: uv run python manage.py test wearables.tests.test_reconnect_authorization_host
Requires Python 3.14, Django, and a dedicated PostgreSQL test database.
"""
from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import WearableConnection, WearableConnectionEvent
from wearables.services.client import RookServiceError
from wearables.services.connections import (
    connection_attempt_origin,
    get_or_create_connection,
    refresh_authorizing_connections,
    start_connection,
)
from wearables.services.identity import get_or_create_rook_identity
from wearables.utils.constants import AuthorizationStatus, ConnectionStatus


@override_settings(
    ROOK_CALLBACK_URL="https://api.example.org/r",
    ROOK_AUTHORIZATION_ALLOWED_HOSTS=["connect.garmin.com"],
    ROOK_CLIENT_UUID="sandbox-client",
    ROOK_SECRET_KEY="sandbox-secret",
    ROOK_BASE_URL="https://api.rook-connect.review",
)
class ReconnectAuthorizationHostTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="rook-reconnect-host-test@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Reconnect", last_name="Host", is_main=True,
        )
        identity = get_or_create_rook_identity(self.profile)
        self.connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity,
            data_source="Garmin", historical_days_requested=7,
        )
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.DISCONNECTED,
            authorization_status=AuthorizationStatus.REVOKED,
            disconnected_at=timezone.now(),
        )
        self.connection.refresh_from_db()
        self.request = SimpleNamespace(
            user=self.user,
            META={"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "Test"},
        )
        self.validated_data = {
            "data_source": "Garmin", "consent_version": "v1", "historical_days": 7,
            "timezone_name": "Asia/Kolkata", "preferred_units": "metric",
        }

    def connect(self):
        return start_connection(
            request=self.request, customer_profile=self.profile,
            validated_data=self.validated_data,
        )

    @override_settings(ROOK_AUTHORIZATION_ALLOWED_HOSTS=[])
    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_unconfigured_hosts_reject_before_changing_disconnected_state(self, authorizer):
        with self.assertRaisesRegex(RookServiceError, "ROOK_AUTHORIZATION_ALLOWED_HOSTS") as failure:
            self.connect()
        self.assertEqual(failure.exception.status_code, 503)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.REVOKED)
        self.assertFalse(WearableConnectionEvent.objects.filter(connection=self.connection).exists())
        authorizer.assert_not_called()

    @patch("wearables.services.connections.enqueue_or_reuse_recovery_job")
    @patch("wearables.services.connections.RookClient.get_authorized_sources", return_value={"Garmin"})
    @patch("wearables.services.client.RookClient.request_json")
    def test_rejected_host_stays_disconnected_then_valid_host_reimports(
        self, authorizer_response, authorized_sources, enqueue_job,
    ):
        authorizer_response.return_value = {
            "authorized": False,
            "authorization_url": "https://untrusted.example/authorize?code=do-not-log",
        }
        with self.assertRaisesRegex(RookServiceError, "untrusted authorization host"):
            self.connect()
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.REVOKED)
        self.assertEqual(self.connection.last_error_code, "rook_authorizer_failed")

        authorizer_response.return_value = {
            "authorized": False,
            "authorization_url": "https://connect.garmin.com/authorize",
        }
        result = self.connect()
        self.assertEqual(result["authorization_url"], "https://connect.garmin.com/authorize")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        refresh_authorizing_connections(self.profile)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.HISTORICAL_REIMPORT)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.AUTHORIZED)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=self.connection, event_type="provider_reconnected",
        ).count(), 1)
        authorized_sources.assert_called_once()
        enqueue_job.assert_called_once()

    def test_previous_failed_reconnect_from_older_build_retains_origin(self):
        WearableConnectionEvent.objects.create(
            connection=self.connection,
            event_type="connection_requested",
            previous_status=ConnectionStatus.DISCONNECTED,
            current_status=ConnectionStatus.CONNECTING,
            actor_user=self.user,
        )
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.PROVIDER_ERROR,
            authorization_status=AuthorizationStatus.ERROR,
            last_error_code="rook_authorizer_failed",
        )
        self.connection.refresh_from_db()
        self.assertEqual(connection_attempt_origin(self.connection), ConnectionStatus.DISCONNECTED)
