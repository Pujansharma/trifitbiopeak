"""Phase 1 release safety regressions: source lifecycle and durable ingestion jobs.

Run with Python 3.14+: uv run python manage.py test wearables.tests.test_phase1_release_safety
These tests deliberately mock external ROOK connectivity, not the Django ORM.
"""
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import call, patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import (
    HealthDomainSnapshot, RookOutbox, RookWebhookReceipt,
    WearableConsent, WearableConnectionEvent,
)
from wearables.services.config import provisioned_sources
from wearables.services.connections import (
    connection_experience_state, get_or_create_connection,
)
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import ingest_rook_document, normalize_health_document
from wearables.services.oauth import callback_url_for_connection, complete_oauth_callback
from wearables.services.notifications import apply_notification_state, process_rook_notification
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus, DocumentStatus,
    HealthJobType, HistoricalImportStatus, PermissionStatus,
)


class ReleaseNotificationStateTests(SimpleTestCase):
    def device(self, *, status=ConnectionStatus.ACTIVE,
               import_status=HistoricalImportStatus.COMPLETED,
               authorization=AuthorizationStatus.AUTHORIZED):
        return SimpleNamespace(
            status=status, import_status=import_status,
            authorization_status=authorization,
            permission_status=PermissionStatus.GRANTED,
            connected_at=timezone.now() - timedelta(days=2),
            last_successful_sync=None, import_started_at=timezone.now(),
            import_completed_at=None,
        )

    def test_repeat_positive_notification_does_not_restart_healthy_import(self):
        device = self.device()
        apply_notification_state(device, "user connected")
        self.assertEqual(device.status, ConnectionStatus.ACTIVE)
        self.assertEqual(device.import_status, HistoricalImportStatus.COMPLETED)

    def test_unauthorized_message_cannot_start_new_import(self):
        device = self.device(
            status=ConnectionStatus.AUTHORIZING,
            authorization=AuthorizationStatus.PENDING,
        )
        apply_notification_state(device, "user unauthorized")
        self.assertEqual(device.status, ConnectionStatus.AUTHORIZATION_EXPIRED)
        self.assertEqual(device.authorization_status, AuthorizationStatus.EXPIRED)

    def test_provider_import_completion_does_not_claim_local_persistence(self):
        device = self.device(
            status=ConnectionStatus.IMPORTING,
            import_status=HistoricalImportStatus.RUNNING,
        )
        apply_notification_state(device, "historical import completed")
        self.assertEqual(device.status, ConnectionStatus.IMPORTING)
        self.assertEqual(device.import_status, HistoricalImportStatus.RUNNING)
        self.assertIsNone(device.import_completed_at)

    def test_expired_authorization_cannot_be_reactivated_by_old_positive_event(self):
        device = self.device(
            status=ConnectionStatus.AUTHORIZATION_EXPIRED,
            authorization=AuthorizationStatus.EXPIRED,
        )
        apply_notification_state(device, "user connected")
        self.assertEqual(device.status, ConnectionStatus.AUTHORIZATION_EXPIRED)
        self.assertEqual(device.authorization_status, AuthorizationStatus.EXPIRED)

    @override_settings(ROOK_SYNC_DELAY_HOURS=48)
    def test_connected_source_with_no_measurements_can_be_stale(self):
        device = self.device(status=ConnectionStatus.IDLE)
        device.connected_at = timezone.now() - timedelta(days=3)
        self.assertEqual(connection_experience_state(device), "sync_delayed")

    @override_settings(ROOK_SYNC_DELAY_HOURS=48)
    def test_recently_connected_source_is_not_falsely_stale(self):
        device = self.device(status=ConnectionStatus.IDLE)
        device.connected_at = timezone.now() - timedelta(minutes=10)
        self.assertEqual(connection_experience_state(device), ConnectionStatus.IDLE)

    @override_settings(ROOK_PROVISIONED_SOURCES=None, SETTINGS_MODULE="core.settings.development")
    @patch("wearables.services.config.config", side_effect=[None, "Garmin,Oura"])
    @patch("wearables.services.config.os.environ.get", return_value=None)
    def test_dev_env_file_source_allowlist_is_read(self, environment_get, config):
        self.assertEqual(provisioned_sources(), {"Garmin", "Oura"})
        self.assertEqual(config.call_args_list, [
            call("ROOK_PROVISIONED_SOURCES", default=None),
            call("DEV_ROOK_PROVISIONED_SOURCES", default=None),
        ])


class ReleaseDurabilityTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="release-safety@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Release", last_name="Safety", is_main=True,
        )
        self.identity = get_or_create_rook_identity(self.profile, timezone_name="UTC")
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=self.user,
            status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now(),
        )
        self.connection = get_or_create_connection(
            customer_profile=self.profile, identity=self.identity,
            data_source="Garmin", historical_days_requested=7,
        )
        self.connection.status = ConnectionStatus.IMPORTING
        self.connection.authorization_status = AuthorizationStatus.AUTHORIZED
        self.connection.permission_status = PermissionStatus.GRANTED
        self.connection.import_status = HistoricalImportStatus.RUNNING
        self.connection.save()

    def payload(self):
        return {
            "client_uuid": "integration-test-client",
            "user_id": self.identity.rook_user_id,
            "datetime": timezone.now().replace(microsecond=0).isoformat(),
            "data_structure": "physical_health_summary",
            "document_version": 1,
            "source_of_data_string": "Garmin",
            "accumulated_steps_int": 8000,
        }

    def test_accepted_webhook_normalizes_inline_without_normalize_job(self):
        result = ingest_rook_document(self.payload(), signature_valid=True)
        self.assertTrue(result["processed"])
        self.assertFalse(result["queued"])
        self.assertFalse(RookOutbox.objects.filter(job_type="normalize_document").exists())
        receipt = RookWebhookReceipt.objects.get(pk=result["documentId"])
        self.assertEqual(receipt.status, DocumentStatus.PROCESSED)
        self.assertNotIn("accumulated_steps_int", receipt.payload)

    def test_normalized_document_refreshes_analytics_inline(self):
        result = ingest_rook_document(self.payload(), signature_valid=True)
        self.assertIn("activity", result["normalize"]["domains"])
        self.assertFalse(RookOutbox.objects.filter(job_type="refresh_analytics").exists())
        self.assertTrue(HealthDomainSnapshot.objects.filter(
            customer_profile=self.profile,
            domain="activity",
        ).exists())

    def test_queued_delivery_is_normalized_once_and_releases_raw_body(self):
        # The orphan sweep was removed on this branch, so a queued delivery is
        # finished by normalizing its receipt directly, as the recovery worker does.
        result = ingest_rook_document(self.payload(), signature_valid=True,
                                      enqueue_normalization=False)
        receipt = RookWebhookReceipt.objects.get(pk=result["documentId"])
        self.assertEqual(receipt.status, DocumentStatus.QUEUED)
        self.assertTrue(receipt.payload)
        with self.captureOnCommitCallbacks(execute=True):
            outcome = normalize_health_document(result["documentId"])
        self.assertFalse(outcome.get("skipped", False))
        second = normalize_health_document(result["documentId"])
        self.assertTrue(second["alreadyProcessed"])
        receipt.refresh_from_db()
        self.assertEqual(receipt.status, DocumentStatus.PROCESSED)
        self.assertNotIn("accumulated_steps_int", receipt.payload)
        self.assertEqual(RookOutbox.objects.filter(job_type="normalize_document").count(), 0)

    def test_out_of_order_old_revoke_cannot_close_fresh_authorization(self):
        self.connection.status = ConnectionStatus.ACTIVE
        self.connection.authorization_status = AuthorizationStatus.AUTHORIZED
        self.connection.import_started_at = timezone.now()
        self.connection.import_status = HistoricalImportStatus.COMPLETED
        self.connection.save()
        result = process_rook_notification({
            "user_id": self.identity.rook_user_id,
            "data_source": "Garmin",
            "action": "user_disconnected",
            "action_datetime": (timezone.now() - timedelta(days=2)).isoformat(),
        }, signature_valid=True)
        self.connection.refresh_from_db()
        self.assertEqual(result["reason"], "out_of_order_notification")
        self.assertEqual(self.connection.status, ConnectionStatus.ACTIVE)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.AUTHORIZED)

    @override_settings(ROOK_CLIENT_UUID="test-client-uuid", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.connections.RookClient")
    def test_callback_commits_state_and_local_authorization_atomically(self, client_class):

        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.import_status = HistoricalImportStatus.NOT_STARTED
        self.connection.save()
        callback = callback_url_for_connection(
            self.connection, actor_user=self.user,
            previous_status=ConnectionStatus.NEVER_CONNECTED,
        )
        client_class.return_value.get_authorized_sources.return_value = {"Garmin"}
        state_token = urlsplit(callback).path.rsplit("/", 1)[-1]
        outcome = complete_oauth_callback(
            state_token, rook_client_uuid="test-client-uuid",
            rook_user_id=self.identity.rook_user_id,
        )
        self.assertEqual(outcome, "authorized")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.IMPORTING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.AUTHORIZED)
        self.assertTrue(WearableConnectionEvent.objects.filter(
            connection=self.connection, event_type="oauth_state_verified",
        ).exists())
        self.assertTrue(RookOutbox.objects.filter(
            connection=self.connection, job_type=HealthJobType.FETCH_ROOK_DATA,
        ).exists())
        self.assertFalse(RookOutbox.objects.filter(
            connection=self.connection, job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
        ).exists())
        client_class.return_value.get_authorized_sources.assert_called_once()

    @override_settings(ROOK_CLIENT_UUID="test-client-uuid", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.connections.enqueue_authorise_rook_connection", side_effect=RuntimeError("transient database error"))
    @patch("wearables.services.connections.RookClient.get_authorized_sources", return_value=set())
    def test_failed_callback_does_not_consume_one_time_token(self, authorized_sources, enqueue):

        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save()
        callback = callback_url_for_connection(
            self.connection, actor_user=self.user,
            previous_status=ConnectionStatus.NEVER_CONNECTED,
        )
        state_token = urlsplit(callback).path.rsplit("/", 1)[-1]
        with self.assertRaises(RuntimeError):
            complete_oauth_callback(
                state_token, rook_client_uuid="test-client-uuid",
                rook_user_id=self.identity.rook_user_id,
            )
        self.assertTrue(WearableConnectionEvent.objects.filter(
            connection=self.connection, event_type="oauth_state_pending",
        ).exists())
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        authorized_sources.assert_called_once()

    @override_settings(ROOK_CLIENT_UUID="test-client-uuid", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.connections.RookClient.get_authorized_sources", return_value=set())
    def test_callback_queues_fallback_only_when_rook_grant_is_not_ready(self, authorized_sources):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.import_status = HistoricalImportStatus.NOT_STARTED
        self.connection.save()
        callback = callback_url_for_connection(
            self.connection,
            actor_user=self.user,
            previous_status=ConnectionStatus.NEVER_CONNECTED,
        )
        outcome = complete_oauth_callback(
            urlsplit(callback).path.rsplit("/", 1)[-1],
            rook_client_uuid="test-client-uuid",
            rook_user_id=self.identity.rook_user_id,
        )
        self.assertEqual(outcome, "pending")
        self.assertTrue(WearableConnectionEvent.objects.filter(
            connection=self.connection,
            event_type="oauth_state_queued",
        ).exists())
        self.assertTrue(RookOutbox.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
        ).exists())
        self.assertFalse(RookOutbox.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.FETCH_ROOK_DATA,
        ).exists())
        authorized_sources.assert_called_once()

    def test_rook_import_completed_notification_waits_for_processing(self):
        self.connection.import_started_at = timezone.now()
        self.connection.save(update_fields=["import_started_at"])
        response = process_rook_notification({
            "user_id": self.identity.rook_user_id,
            "data_source": "Garmin",
            "action": "historical_import_completed",
            "action_datetime": timezone.now().isoformat(),
        }, signature_valid=True)
        self.connection.refresh_from_db()
        self.assertEqual(response["status"], ConnectionStatus.IMPORTING)
        self.assertEqual(self.connection.import_status, HistoricalImportStatus.RUNNING)
        self.assertTrue(RookOutbox.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.FETCH_ROOK_DATA,
        ).exists())

    def test_positive_notification_on_provider_error_queues_verification_not_authorize(self):
        self.connection.status = ConnectionStatus.PROVIDER_ERROR
        self.connection.authorization_status = AuthorizationStatus.ERROR
        self.connection.import_status = HistoricalImportStatus.NOT_STARTED
        self.connection.import_started_at = None
        self.connection.save()
        response = process_rook_notification({
            "user_id": self.identity.rook_user_id,
            "data_source": "Garmin",
            "action": "user_connected",
            "action_datetime": timezone.now().isoformat(),
        }, signature_valid=True)
        self.connection.refresh_from_db()
        self.assertTrue(response.get("authorizationQueued"))
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.PENDING)
        self.assertTrue(RookOutbox.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
        ).exists())
        self.assertFalse(RookOutbox.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.FETCH_ROOK_DATA,
        ).exists())

    def test_positive_notification_on_never_connected_queues_verification(self):
        self.connection.status = ConnectionStatus.NEVER_CONNECTED
        self.connection.authorization_status = AuthorizationStatus.NOT_STARTED
        self.connection.import_status = HistoricalImportStatus.NOT_STARTED
        self.connection.save()
        response = process_rook_notification({
            "user_id": self.identity.rook_user_id,
            "data_source": "Garmin",
            "action": "authorization_completed",
            "action_datetime": timezone.now().isoformat(),
        }, signature_valid=True)
        self.connection.refresh_from_db()
        self.assertTrue(response.get("authorizationQueued"))
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.PENDING)
