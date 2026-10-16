"""PRD Foundation + 10.x failure-mode regressions.

These tests require the project's supported Python, Django, and a test DB.
They deliberately do not mock ROOK for real live integration acceptance.
"""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import RookHealthDocument, WearableConsent
from wearables.services.analytics import card_state, connection_priority_state, trend_payload
from wearables.services.connections import disconnect_connection, get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import ingest_rook_document
from wearables.services.lifecycle import (
    can_ingest_source, source_permission_for_domain, valid_transition,
)
from wearables.services.notifications import apply_notification_state
from wearables.utils.constants import (
    AuthorizationStatus, ConfidenceLevel, ConnectionStatus, ConsentStatus,
    HealthCardState, HistoricalImportStatus, PermissionStatus,
)


def connection_stub(source="Garmin", *, status=ConnectionStatus.ACTIVE,
                    authorization=AuthorizationStatus.AUTHORIZED,
                    permission=PermissionStatus.GRANTED, capabilities=None):
    return SimpleNamespace(
        data_source=source, status=status, authorization_status=authorization,
        permission_status=permission, capabilities=capabilities or [],
        disconnected_at=None, last_error_code="", import_status=HistoricalImportStatus.COMPLETED,
        last_successful_sync=timezone.now(), connected_at=timezone.now(),
    )


class ConnectionStateMachineTests(SimpleTestCase):
    def test_reconnect_requires_authorization_states(self):
        self.assertFalse(valid_transition(ConnectionStatus.DISCONNECTED, ConnectionStatus.ACTIVE))
        self.assertTrue(valid_transition(ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZING))
        self.assertTrue(valid_transition(ConnectionStatus.AUTHORIZING, ConnectionStatus.RECONNECTED))
        self.assertTrue(valid_transition(ConnectionStatus.RECONNECTED, ConnectionStatus.HISTORICAL_REIMPORT))
        self.assertTrue(valid_transition(ConnectionStatus.HISTORICAL_REIMPORT, ConnectionStatus.ACTIVE))

    def test_inactive_and_expired_sources_cannot_write_data(self):
        for status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.AUTHORIZATION_EXPIRED,
                       ConnectionStatus.NEVER_CONNECTED, ConnectionStatus.AUTHORIZING):
            with self.subTest(status=status):
                self.assertFalse(can_ingest_source(connection_stub(status=status)))
        self.assertFalse(can_ingest_source(connection_stub(
            authorization=AuthorizationStatus.REVOKED,
        )))
        self.assertFalse(can_ingest_source(connection_stub(permission=PermissionStatus.DENIED)))
        self.assertTrue(can_ingest_source(connection_stub(status=ConnectionStatus.HISTORICAL_REIMPORT)))

    def test_sdk_partial_scopes_only_block_affected_domain(self):
        source = connection_stub("Apple Health", status=ConnectionStatus.PARTIAL,
                                 permission=PermissionStatus.LIMITED, capabilities=["sleep"])
        self.assertEqual(source_permission_for_domain(source, "sleep"), "granted")
        self.assertEqual(source_permission_for_domain(source, "activity"), "denied")
        self.assertIsNone(connection_priority_state([source], "sleep"))
        self.assertEqual(connection_priority_state([source], "activity"),
                         HealthCardState.PERMISSION_REQUIRED)

    def test_one_broken_provider_does_not_block_healthy_source(self):
        broken = connection_stub(status=ConnectionStatus.AUTHORIZATION_EXPIRED)
        healthy = connection_stub("Oura")
        self.assertIsNone(connection_priority_state([broken, healthy], "sleep"))
        self.assertTrue(can_ingest_source(healthy))

    def test_upstream_account_closed_requires_another_provider(self):
        device = connection_stub()
        apply_notification_state(device, "provider account deleted")
        self.assertEqual(device.status, ConnectionStatus.DISCONNECTED)
        self.assertEqual(device.last_error_code, "provider_account_closed")
        self.assertFalse(can_ingest_source(device))

    def test_outdated_positive_notification_cannot_reactivate_disconnected_source(self):
        device = connection_stub(status=ConnectionStatus.DISCONNECTED)
        apply_notification_state(device, "authorization completed")
        self.assertEqual(device.status, ConnectionStatus.DISCONNECTED)


class DomainAvailabilityTests(SimpleTestCase):
    @staticmethod
    def summaries(days, *, start=date(2026, 10, 1)):
        return [SimpleNamespace(metric="steps", maximum=6000, local_date=start + timedelta(days=i),
                                last_observed_at=None) for i in range(days)]

    @override_settings(HEALTH_MIN_BASELINE_DAYS=7, HEALTH_TREND_MINIMUM_OBSERVATIONS=7)
    def test_seven_days_no_prior_baseline_cannot_claim_trend_available(self):
        summaries = self.summaries(7)
        trend = trend_payload(summaries=summaries, metric="steps",
                              confidence=ConfidenceLevel.HIGH, preferred_units="metric",
                              today=date(2026, 10, 14))
        state = card_state(domain="activity", summaries=summaries, connections=[],
                           coverage={"missingDays": 0}, trend=trend)
        self.assertEqual(state, HealthCardState.CURRENT_VALUE_ONLY)
        self.assertFalse(trend["baseline"]["available"])

    @override_settings(HEALTH_MIN_BASELINE_DAYS=7, HEALTH_TREND_MINIMUM_OBSERVATIONS=7)
    def test_fourteen_days_with_comparison_can_have_trend(self):
        summaries = self.summaries(14)
        trend = trend_payload(summaries=summaries, metric="steps",
                              confidence=ConfidenceLevel.HIGH, preferred_units="metric",
                              today=date(2026, 10, 14))
        self.assertTrue(trend["baseline"]["available"])
        self.assertEqual(card_state(domain="activity", summaries=summaries, connections=[],
                                    coverage={"missingDays": 0}, trend=trend),
                         HealthCardState.TREND_AVAILABLE)

    def test_silent_provider_is_waiting_not_unsupported(self):
        connection = connection_stub("Polar")
        self.assertEqual(card_state(domain="sleep", summaries=[], connections=[connection],
                                    coverage={"missingDays": 0}),
                         HealthCardState.WAITING_FOR_DATA)


class IngestionSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="phase1-completion-safety@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(customer=customer, first_name="Phase", last_name="Safety", is_main=True)
        self.identity = get_or_create_rook_identity(self.profile)
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=self.user,
            status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now(),
        )
        self.garmin = self.add_source("Garmin")

    def add_source(self, source):
        connection = get_or_create_connection(
            customer_profile=self.profile, identity=self.identity,
            data_source=source, historical_days_requested=7,
        )
        connection.status = ConnectionStatus.ACTIVE
        connection.authorization_status = AuthorizationStatus.AUTHORIZED
        connection.permission_status = PermissionStatus.GRANTED
        connection.save()
        return connection

    def payload(self, source):
        return {
            "client_uuid": "test-client", "user_id": self.identity.rook_user_id,
            "datetime": "2026-10-09T09:00:00Z", "data_structure": "physical_health_summary",
            "document_version": 1, "source_of_data_string": source,
            "accumulated_steps_int": 6500,
        }

    @patch("wearables.services.connections.RookClient.revoke_source")
    def test_disconnect_blocks_garmin_but_preserves_second_source(self, revoke):
        self.add_source("Oura")
        with self.captureOnCommitCallbacks(execute=True):
            disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        garmin_result = ingest_rook_document(self.payload("Garmin"), signature_valid=True)
        self.assertEqual(garmin_result["reason"], "inactive_or_unpermitted_source")
        with self.captureOnCommitCallbacks(execute=True):
            oura_result = ingest_rook_document(self.payload("Oura"), signature_valid=True)
        self.assertTrue(oura_result.get("queued"))
        self.assertEqual(RookHealthDocument.objects.count(), 1)
        revoke.assert_called_once()

    @patch("wearables.services.connections.RookClient.revoke_source")
    def test_revoked_source_cannot_be_restarted_by_delayed_replay(self, revoke):
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        first = ingest_rook_document(self.payload("Garmin"), signature_valid=True)
        replay = ingest_rook_document(self.payload("Garmin"), signature_valid=True)
        self.assertTrue(first.get("skipped"))
        self.assertEqual(RookHealthDocument.objects.count(), 0)
        self.assertTrue(replay.get("duplicate"))

    def test_unknown_source_does_not_create_unapproved_connection(self):
        result = ingest_rook_document(self.payload("Fitbit"), signature_valid=True)
        self.assertEqual(result["reason"], "unlinked_source")
        self.assertEqual(RookHealthDocument.objects.count(), 0)
