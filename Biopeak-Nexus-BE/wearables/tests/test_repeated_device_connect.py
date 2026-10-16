"""PRD 10.1-10.3: a second Connect tap cannot rewind an OAuth handoff.

Requires the project's supported Python/Django/PostgreSQL test environment.
The ROOK authorizer is mocked; live provider verification remains separate.
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
    get_or_create_connection,
    start_connection,
    refresh_authorizing_connections,
)
from wearables.services.identity import get_or_create_rook_identity
from wearables.utils.constants import AuthorizationStatus, ConnectionStatus


@override_settings(ROOK_CALLBACK_URL="https://api.example.org/r")
class RepeatedDeviceConnectTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="phase1-retry@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Repeat", last_name="Connect", is_main=True,
        )
        self.request = SimpleNamespace(
            user=self.user,
            META={"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "Biopeak test"},
        )
        self.validated_data = {
            "data_source": "Garmin", "consent_version": "v1", "historical_days": 7,
            "timezone_name": "Asia/Kolkata", "preferred_units": "metric",
        }

    def start(self):
        return start_connection(
            request=self.request, customer_profile=self.profile,
            validated_data=self.validated_data,
        )

    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_second_connect_preserves_authorizing_and_supersedes_old_token(self, authorizer):
        authorizer.return_value = {
            "authorized": False, "authorization_url": "https://connect.garmin.com/one",
        }
        self.start()
        connection = WearableConnection.objects.get(customer_profile=self.profile, data_source="Garmin")
        self.assertEqual(connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_pending",
        ).count(), 1)

        second = self.start()
        connection.refresh_from_db()
        self.assertEqual(second["authorization_url"], "https://connect.garmin.com/one")
        self.assertEqual(connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(connection.authorization_status, AuthorizationStatus.PENDING)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="connection_requested",
        ).count(), 1)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_superseded",
        ).count(), 1)
        new_state = WearableConnectionEvent.objects.get(
            connection=connection, event_type="oauth_state_pending",
        )
        self.assertEqual(new_state.previous_status, ConnectionStatus.NEVER_CONNECTED)
        authorizer.assert_called()

    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_failed_link_refresh_does_not_cancel_previous_authorizing_attempt(self, authorizer):
        authorizer.side_effect = [
            {"authorized": False, "authorization_url": "https://connect.garmin.com/one"},
            RookServiceError("Provider temporarily unavailable."),
        ]
        self.start()
        with self.assertRaises(RookServiceError):
            self.start()
        connection = WearableConnection.objects.get(customer_profile=self.profile, data_source="Garmin")
        self.assertEqual(connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_pending",
        ).count(), 1)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_authorizer_failed",
        ).count(), 1)

    @patch("wearables.services.connections.enqueue_health_job")
    @patch("wearables.services.connections.RookClient.get_authorized_sources", return_value={"Garmin"})
    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_repeated_reconnect_preserves_reimport_origin(self, authorizer, sources, enqueue):
        identity = get_or_create_rook_identity(self.profile)
        connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity,
            data_source="Garmin", historical_days_requested=7,
        )
        connection.status = ConnectionStatus.DISCONNECTED
        connection.authorization_status = AuthorizationStatus.REVOKED
        connection.disconnected_at = timezone.now()
        connection.save()
        authorizer.return_value = {
            "authorized": False, "authorization_url": "https://connect.garmin.com/one",
        }
        self.start()
        self.start()
        refresh_authorizing_connections(self.profile)
        connection.refresh_from_db()
        self.assertEqual(connection.status, ConnectionStatus.HISTORICAL_REIMPORT)
        self.assertEqual(connection.authorization_status, AuthorizationStatus.AUTHORIZED)
        self.assertEqual(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="provider_reconnected",
        ).count(), 1)
        enqueue.assert_called_once()
        sources.assert_called_once()

    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_second_connect_is_noop_if_already_authorized(self, authorizer):
        identity = get_or_create_rook_identity(self.profile)
        connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity,
            data_source="Garmin", historical_days_requested=7,
        )
        connection.status = ConnectionStatus.ACTIVE
        connection.authorization_status = AuthorizationStatus.AUTHORIZED
        connection.save()
        result = self.start()
        self.assertIsNone(result["authorization_url"])
        connection.refresh_from_db()
        self.assertEqual(connection.status, ConnectionStatus.ACTIVE)
        authorizer.assert_not_called()

    @patch("wearables.services.connections.RookClient.get_authorizer")
    def test_concurrent_disconnect_does_not_reopen_connection(self, authorizer):
        def disconnect_during_request(**kwargs):
            connection = WearableConnection.objects.get(
                customer_profile=self.profile, data_source="Garmin",
            )
            connection.status = ConnectionStatus.DISCONNECTED
            connection.authorization_status = AuthorizationStatus.REVOKED
            connection.disconnected_at = timezone.now()
            connection.save(update_fields=[
                "status", "authorization_status", "disconnected_at", "updated_at",
            ])
            return {"authorized": False, "authorization_url": "https://connect.garmin.com/one"}

        authorizer.side_effect = disconnect_during_request
        result = self.start()
        self.assertEqual(result["connection"].status, ConnectionStatus.DISCONNECTED)
        self.assertIsNone(result["authorization_url"])
        connection = WearableConnection.objects.get(customer_profile=self.profile, data_source="Garmin")
        self.assertEqual(connection.status, ConnectionStatus.DISCONNECTED)
