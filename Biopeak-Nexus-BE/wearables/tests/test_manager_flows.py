"""PostgreSQL integration tests for the manager's four diagram flows.

Run AFTER the repository owner generates/reviews the wearable migrations:
python manage.py test wearables.tests.test_manager_flows
All provider calls are mocked; these tests never contact ROOK.
"""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from datetime import timedelta
from uuid import uuid4
from unittest.mock import patch

from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase, override_settings, skipUnlessDBFeature
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import RookOutbox, RookMemberIdentity, WearableConsent, WearableConnection
from wearables.services.authorization_jobs import process_authorise_rook_connection, process_revoke_rook_connection
from wearables.services.client import RookServiceError
from wearables.services.connections import disconnect_connection
from wearables.services.job_claims import (
    claim_health_job, complete_health_job, defer_health_job, fail_health_job, LostHealthJobLease,
)
from wearables.services.job_queue import enqueue_authorise_rook_connection, enqueue_or_reuse_fetch_rook_data_job
from wearables.services.recovery import process_fetch_rook_data
from wearables.services.notifications import process_rook_notification
from wearables.services.scheduling import run_rook_sync_scan
from wearables.services.sync_policy import ManualSyncCooldown
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionMethod, ConnectionStatus, ConsentStatus,
    HealthJobStatus, HealthJobType, HistoricalImportStatus, PermissionStatus,
)


@override_settings(ROOK_PREEXISTING_ENABLED=True, ROOK_SYNC_UNITS_PER_RUN=21,
                   ROOK_AUTH_OUTBOX_QUEUE_URL="", ROOK_DATA_FETCH_OUTBOX_QUEUE_URL="")
class ManagerFlowTests(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(email="manager-flow@example.test")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(customer=customer, first_name="Flow", last_name="Test", is_main=True)
        self.identity = RookMemberIdentity.objects.create(customer_profile=self.profile, rook_user_id=f"test-{uuid4().hex}", timezone_name="Asia/Kolkata")
        WearableConsent.objects.create(customer_profile=self.profile, granted_by=self.user,
                                      status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now())
        self.connection = WearableConnection.objects.create(
            customer_profile=self.profile, identity=self.identity, data_source="Garmin",
            connection_method=ConnectionMethod.API, status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED, permission_status=PermissionStatus.GRANTED,
            historical_days_requested=7, connected_at=timezone.now(),
        )

    def queued_sync(self, *, flow="initial"):
        job, created = enqueue_or_reuse_fetch_rook_data_job(connection=self.connection, customer_profile=self.profile,
                                                     manual=True, flow=flow)
        self.assertTrue(created)
        return job

    def retry(self, job):
        fail_health_job(job, RookServiceError("temporary upstream failure"))
        RookOutbox.objects.filter(pk=job.pk).update(scheduled_at=timezone.now())
        return claim_health_job(job.pk)

    def test_repeated_manual_sync_reuses_one_job_and_frozen_window(self) -> None:
        first = self.queued_sync(flow="manual")
        with self.assertRaises(ManualSyncCooldown) as caught:
            enqueue_or_reuse_fetch_rook_data_job(connection=self.connection, customer_profile=self.profile,
                                         manual=True, flow="manual")
        self.assertEqual(caught.exception.job_id, first.pk)
        first.refresh_from_db()
        self.assertEqual(RookOutbox.objects.filter(job_type=HealthJobType.FETCH_ROOK_DATA).count(), 1)

    def test_revoked_consent_does_not_enqueue_a_pull(self) -> None:
        WearableConsent.objects.filter(customer_profile=self.profile).update(status=ConsentStatus.REVOKED, revoked_at=timezone.now())
        job, created = enqueue_or_reuse_fetch_rook_data_job(connection=self.connection, customer_profile=self.profile, manual=True)
        self.assertIsNone(job)
        self.assertFalse(created)

    @patch("wearables.services.recovery.refresh_profile_snapshots", return_value=[])
    @patch("wearables.services.recovery.RookClient")
    def test_initial_pull_uses_21_requests_then_updates_last_sync(self, client, analytics) -> None:
        client.return_value.get_processed_summaries.return_value = []
        queued = self.queued_sync()
        claimed = claim_health_job(queued.pk)
        result = process_fetch_rook_data(claimed)
        self.assertTrue(result["synced"])
        self.assertEqual(client.return_value.get_processed_summaries.call_count, 21)
        self.connection.refresh_from_db()
        self.assertIsNotNone(self.connection.last_successful_sync)
        self.assertEqual(self.connection.synced_through.isoformat(), claimed.payload["sync"]["windowEnd"])
        analytics.assert_called_once()

    @patch("wearables.services.recovery.RookClient")
    def test_partial_fetch_does_not_advance_last_sync_and_retry_resumes(self, client) -> None:
        claimed = claim_health_job(self.queued_sync().pk)
        client.return_value.get_processed_summaries.side_effect = [[], RookServiceError("unavailable")]
        with self.assertRaises(RookServiceError):
            process_fetch_rook_data(claimed)
        self.connection.refresh_from_db()
        self.assertIsNone(self.connection.synced_through)
        self.assertIsNone(self.connection.last_successful_sync)
        claimed.refresh_from_db()
        self.assertEqual(claimed.payload["sync"]["nextPillar"], 1)
        retried = self.retry(claimed)
        client.return_value.get_processed_summaries.side_effect = None
        client.return_value.get_processed_summaries.return_value = []
        with patch("wearables.services.recovery.refresh_profile_snapshots", return_value=[]):
            process_fetch_rook_data(retried)
        self.assertEqual(client.return_value.get_processed_summaries.call_args_list[2].kwargs["health_pillar"], "sleep")
        self.assertEqual(client.return_value.get_processed_summaries.call_count, 22)

    @patch("wearables.services.recovery.RookClient")
    def test_analytics_failure_retries_without_refetching(self, client) -> None:
        client.return_value.get_processed_summaries.return_value = []
        claimed = claim_health_job(self.queued_sync().pk)
        with patch("wearables.services.recovery.refresh_profile_snapshots", side_effect=ValueError("analytics failed")):
            with self.assertRaises(ValueError):
                process_fetch_rook_data(claimed)
        self.connection.refresh_from_db()
        self.assertIsNone(self.connection.synced_through)
        retried = self.retry(claimed)
        with patch("wearables.services.recovery.refresh_profile_snapshots", return_value=[]):
            process_fetch_rook_data(retried)
        self.assertEqual(client.return_value.get_processed_summaries.call_count, 21)

    @override_settings(ROOK_SYNC_UNITS_PER_RUN=1)
    @patch("wearables.services.recovery.RookClient")
    def test_bounded_continuation_preserves_progress_without_spending_retries(self, client) -> None:
        client.return_value.get_processed_summaries.return_value = []
        claimed = claim_health_job(self.queued_sync().pk)
        result = process_fetch_rook_data(claimed)
        self.assertTrue(result["deferred"])
        defer_health_job(claimed, result)
        claimed.refresh_from_db()
        self.assertEqual(claimed.status, HealthJobStatus.PENDING)
        self.assertEqual(claimed.attempt_count, 0)
        self.assertEqual(claimed.payload["sync"]["requestCount"], 1)

    @patch("wearables.services.authorization_jobs.RookClient")
    def test_authorization_job_queues_initial_pull_only_after_server_verification(self, client) -> None:
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save()
        queued = enqueue_authorise_rook_connection(connection=self.connection)
        self.assertFalse(RookOutbox.objects.filter(job_type=HealthJobType.FETCH_ROOK_DATA).exists())
        client.return_value.get_authorized_sources.return_value = {"Garmin"}
        result = process_authorise_rook_connection(claim_health_job(queued.pk))
        self.assertTrue(result["authorized"])
        pull = RookOutbox.objects.get(job_type=HealthJobType.FETCH_ROOK_DATA)
        self.assertEqual(pull.payload["sync"]["flow"], "initial")

    @patch("wearables.services.authorization_jobs.RookClient")
    def test_pending_provider_authorization_is_deferred_not_fake_success(self, client) -> None:
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save()
        client.return_value.get_authorized_sources.return_value = set()
        result = process_authorise_rook_connection(claim_health_job(enqueue_authorise_rook_connection(connection=self.connection).pk))
        self.assertTrue(result["deferred"])
        self.assertFalse(RookOutbox.objects.filter(job_type=HealthJobType.FETCH_ROOK_DATA).exists())

    @patch("wearables.services.authorization_jobs.RookClient")
    @patch("wearables.services.connections.RookClient")
    def test_revoke_is_immediate_locally_and_remote_call_only_occurs_in_worker(self, connect_client, revoke_client) -> None:
        sync = claim_health_job(self.queued_sync().pk)
        connection, pending = disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        self.assertTrue(pending)
        connect_client.assert_not_called()
        self.assertEqual(connection.authorization_status, AuthorizationStatus.REVOKED)
        sync.refresh_from_db()
        self.assertEqual(sync.status, HealthJobStatus.FAILED)
        job = RookOutbox.objects.get(job_type=HealthJobType.REVOKE_ROOK_CONNECTION)
        revoke_client.return_value.get_authorized_sources.return_value = {"Garmin"}
        claimed = claim_health_job(job.pk)
        result = process_revoke_rook_connection(claimed)
        self.assertTrue(result["deferred"])
        defer_health_job(claimed, result)
        RookOutbox.objects.filter(pk=job.pk).update(scheduled_at=timezone.now())
        revoke_client.return_value.get_authorized_sources.return_value = set()
        result = process_revoke_rook_connection(claim_health_job(job.pk))
        self.assertTrue(result["revoked"])
        revoke_client.return_value.revoke_source.assert_called_once()
        connection.refresh_from_db()
        self.assertEqual(connection.last_error_code, "")
        self.assertEqual(connection.status, ConnectionStatus.DISCONNECTED)

    def test_late_worker_cannot_complete_after_revoke(self) -> None:
        claimed = claim_health_job(self.queued_sync().pk)
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        self.assertFalse(complete_health_job(claimed, {"synced": True}))
        self.connection.refresh_from_db()
        self.assertIsNone(self.connection.synced_through)

    def test_nightly_only_selects_stale_connections_in_default_mode(self) -> None:
        self.connection.synced_through = timezone.now() - timedelta(days=8)
        self.connection.save()
        result = run_rook_sync_scan()
        self.assertEqual(result["enqueuedCount"], 1)
        self.assertFalse(result.get("deferred"))
        again = run_rook_sync_scan()
        self.assertEqual(again["enqueuedCount"], 0)
        self.assertEqual(
            RookOutbox.objects.get(job_type=HealthJobType.FETCH_ROOK_DATA).payload["sync"]["flow"],
            "nightly",
        )

    def test_nightly_does_not_schedule_recently_synced_connection(self) -> None:
        self.connection.synced_through = timezone.now() - timedelta(days=1)
        self.connection.save()
        result = run_rook_sync_scan()
        self.assertEqual(result["enqueuedCount"], 0)

    def test_two_claims_cannot_own_one_job(self) -> None:
        job = self.queued_sync()
        self.assertIsNotNone(claim_health_job(job.pk))
        self.assertIsNone(claim_health_job(job.pk))

    def test_retry_is_fenced_from_old_attempt(self) -> None:
        old = claim_health_job(self.queued_sync().pk)
        new = self.retry(old)
        self.assertNotEqual(new.claim_token, old.claim_token)
        self.assertFalse(complete_health_job(old, {}))
        self.assertTrue(complete_health_job(new, {}))

@override_settings(ROOK_PREEXISTING_ENABLED=True)
class RevocationNotificationTests(TestCase):
    setUp = ManagerFlowTests.setUp

    def test_late_notification_does_not_clear_pending_revoke(self) -> None:
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        response = process_rook_notification({
            "user_id": self.identity.rook_user_id, "data_source": "Garmin",
            "action": "user_disconnected", "action_datetime": timezone.now().isoformat(),
        }, signature_valid=True)
        self.assertEqual(response["reason"], "revocation_pending")
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.last_error_code, "revoke_pending")

    def test_explicit_revoke_retry_reactivates_failed_remote_job(self) -> None:
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        job = RookOutbox.objects.get(job_type=HealthJobType.REVOKE_ROOK_CONNECTION)
        RookOutbox.objects.filter(pk=job.pk).update(status=HealthJobStatus.FAILED, attempt_count=1)
        disconnect_connection(customer_profile=self.profile, data_source="Garmin", actor_user=self.user)
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.PENDING)
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(RookOutbox.objects.filter(job_type=HealthJobType.REVOKE_ROOK_CONNECTION).count(), 1)


def concurrent_claim(job_id, barrier):
    close_old_connections()
    try:
        barrier.wait(timeout=10)
        claimed = claim_health_job(job_id)
        return claimed.claim_token if claimed else None
    finally:
        close_old_connections()


def concurrent_sync_enqueue(connection_id, profile_id, barrier):
    close_old_connections()
    try:
        source = WearableConnection.objects.get(pk=connection_id)
        profile = CustomerProfile.objects.get(pk=profile_id)
        barrier.wait(timeout=10)
        try:
            job, created = enqueue_or_reuse_fetch_rook_data_job(connection=source, customer_profile=profile, manual=True, flow="manual")
            return job.pk, created
        except ManualSyncCooldown as error:
            return error.job_id, False
    finally:
        close_old_connections()


@override_settings(ROOK_PREEXISTING_ENABLED=True)
class ManagerFlowConcurrencyTests(TransactionTestCase):
    setUp = ManagerFlowTests.setUp

    @skipUnlessDBFeature("has_select_for_update")
    def test_simultaneous_workers_only_claim_once(self) -> None:
        job = RookOutbox.objects.create(job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
            idempotency_key="simultaneous-claim", scheduled_at=timezone.now())
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(concurrent_claim, job.pk, barrier) for _ in range(2)]
            claims = [future.result(timeout=20) for future in futures]
        self.assertEqual(sum(token is not None for token in claims), 1)

    @skipUnlessDBFeature("has_select_for_update")
    def test_simultaneous_sync_requests_create_one_open_job(self) -> None:
        barrier = Barrier(2)
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(concurrent_sync_enqueue, self.connection.pk, self.profile.pk, barrier) for _ in range(2)]
            results = [future.result(timeout=20) for future in futures]
        self.assertEqual(len({result[0] for result in results}), 1)
        self.assertEqual(sum(result[1] for result in results), 1)
