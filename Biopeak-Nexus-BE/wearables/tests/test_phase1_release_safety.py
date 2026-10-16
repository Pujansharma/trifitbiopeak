"""Phase 1 release safety regressions: source lifecycle and durable ingestion jobs.

Run with Python 3.14+: uv run python manage.py test wearables.tests.test_phase1_release_safety
These tests deliberately mock external ROOK connectivity, not the Django ORM.
"""
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import (
    HealthProcessingJob, RookHealthDocument, WearableConsent,
)
from wearables.services.config import provisioned_sources
from wearables.services.connections import (
    connection_experience_state, get_or_create_connection,
)
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import ingest_rook_document, normalize_health_document
from wearables.services.job_processor import enqueue_orphaned_normalization_jobs
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
    @patch("wearables.services.config.config", return_value="Garmin,Oura")
    @patch("wearables.services.config.os.environ.get", return_value=None)
    def test_dev_env_file_source_allowlist_is_read(self, environment_get, config):
        self.assertEqual(provisioned_sources(), {"Garmin", "Oura"})
        config.assert_called_once_with("DEV_ROOK_PROVISIONED_SOURCES", default=None)


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

    def test_accepted_webhook_and_normalization_job_are_one_transaction(self):
        result = ingest_rook_document(self.payload(), signature_valid=True)
        self.assertTrue(result["queued"])
        self.assertTrue(HealthProcessingJob.objects.filter(
            document_id=result["documentId"],
            job_type=HealthJobType.NORMALIZE_DOCUMENT,
        ).exists())
        self.assertEqual(RookHealthDocument.objects.get(pk=result["documentId"]).status,
                         DocumentStatus.QUEUED)

    def test_normalized_document_has_durable_analytics_refresh(self):
        result = ingest_rook_document(self.payload(), signature_valid=True)
        with self.captureOnCommitCallbacks(execute=True):
            normalized = normalize_health_document(result["documentId"])
        self.assertIn("activity", normalized["domains"])
        self.assertTrue(HealthProcessingJob.objects.filter(
            document_id=result["documentId"],
            job_type=HealthJobType.REFRESH_ANALYTICS,
        ).exists())

    def test_missing_normalization_job_is_recovered_once(self):
        result = ingest_rook_document(self.payload(), signature_valid=True,
                                      enqueue_normalization=False)
        document = RookHealthDocument.objects.get(pk=result["documentId"])
        document.received_at = timezone.now() - timedelta(minutes=20)
        document.save(update_fields=["received_at"])
        recovery = enqueue_orphaned_normalization_jobs(grace_minutes=10)
        self.assertEqual(recovery["queued"], 1)
        self.assertEqual(enqueue_orphaned_normalization_jobs(grace_minutes=10)["queued"], 0)
        self.assertEqual(HealthProcessingJob.objects.filter(
            document=document, job_type=HealthJobType.NORMALIZE_DOCUMENT,
        ).count(), 1)

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
    @patch("wearables.services.oauth.RookClient")
    def test_callback_commits_state_and_local_authorization_atomically(self, client_class):
        from urllib.parse import urlsplit
        from wearables.models import WearableConnectionEvent
        from wearables.services.oauth import callback_url_for_connection, complete_oauth_callback

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
        self.assertTrue(HealthProcessingJob.objects.filter(
            connection=self.connection, job_type=HealthJobType.RECOVERY_PULL,
        ).exists())
        client_class.return_value.get_authorized_sources.assert_called_once()

    @override_settings(ROOK_CLIENT_UUID="test-client-uuid", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.oauth.RookClient")
    @patch("wearables.services.connections.authorization_confirmed", side_effect=RuntimeError("transient database error"))
    def test_failed_callback_does_not_consume_one_time_token(self, confirm, client_class):
        from urllib.parse import urlsplit
        from wearables.models import WearableConnectionEvent
        from wearables.services.oauth import callback_url_for_connection, complete_oauth_callback

        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save()
        callback = callback_url_for_connection(
            self.connection, actor_user=self.user,
            previous_status=ConnectionStatus.NEVER_CONNECTED,
        )
        client_class.return_value.get_authorized_sources.return_value = {"Garmin"}
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
        self.assertTrue(HealthProcessingJob.objects.filter(
            connection=self.connection,
            job_type=HealthJobType.RECOVERY_PULL,
        ).exists())
