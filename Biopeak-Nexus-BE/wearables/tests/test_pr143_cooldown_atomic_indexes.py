"""Regression coverage for reviewer follow-ups on cooldowns, atomic reconnect and indexes.

Runs under the project's Python 3.14/Django/PostgreSQL test environment.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import WearableConsent, RookOutbox, WearableConnection, WearableConnectionEvent
from wearables.services.client import RookServiceError
from wearables.services.connections import authorization_confirmed, get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.job_claims import fail_health_job, reset_stale_health_jobs
from wearables.services.job_queue import (
    enqueue_or_reuse_fetch_rook_data_job, open_fetch_rook_data_jobs,
)
from wearables.services.scheduling import eligible_nightly_connections
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus, HealthJobStatus, HealthJobType,
    HistoricalImportStatus, MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
)


class CooldownAndAtomicRecoveryTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="cooldown-atomic@example.com")
        UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Cooldown", last_name="Atomic", is_main=True,
        )
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=user, status=ConsentStatus.GRANTED,
            version="v1", granted_at=timezone.now(),
        )
        identity = get_or_create_rook_identity(self.profile)
        self.connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity,
            data_source="Garmin", historical_days_requested=7,
        )
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            last_successful_sync=timezone.now(),
            import_status=HistoricalImportStatus.COMPLETED,
        )
        self.connection.refresh_from_db()

    def test_recovery_cooldown_uses_finish_time_even_if_created_hours_ago(self):
        self.connection.last_successful_sync = None
        self.connection.save(update_fields=["last_successful_sync", "updated_at"])
        job = RookOutbox.objects.create(
            connection=self.connection, customer_profile=self.profile,
            job_type=HealthJobType.FETCH_ROOK_DATA, idempotency_key="old-recovery-finished-now",
            status=HealthJobStatus.COMPLETED,
            scheduled_at=timezone.now() - timedelta(hours=3),
            completed_at=timezone.now(),
        )
        existing, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertIsNone(existing)
        self.assertFalse(created)
        job.completed_at = timezone.now() - timedelta(hours=2)
        job.save(update_fields=["completed_at", "updated_at"])
        existing, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        self.assertEqual(existing.status, HealthJobStatus.PENDING)

    def test_unfinished_recovery_remains_excluded_regardless_of_age(self):
        self.connection.last_successful_sync = None
        self.connection.save(update_fields=["last_successful_sync", "updated_at"])
        running_job = RookOutbox.objects.create(
            connection=self.connection, customer_profile=self.profile,
            job_type=HealthJobType.FETCH_ROOK_DATA, idempotency_key="slow-recovery",
            status=HealthJobStatus.RUNNING,
            scheduled_at=timezone.now() - timedelta(hours=3),
        )
        self.assertTrue(open_fetch_rook_data_jobs(self.connection).filter(pk=running_job.pk).exists())
        existing, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertEqual(existing.pk, running_job.pk)
        self.assertFalse(created)

    def test_nightly_eligibility_uses_sync_coverage_not_import_start(self):
        now = timezone.now()
        payload = {
            "mode": "stale",
            "cutoff": (now - timedelta(days=7)).isoformat(),
            "cursor": None,
        }
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.PARTIAL,
            import_status=HistoricalImportStatus.RUNNING,
            import_started_at=None,
            last_successful_sync=now,
            synced_through=None,
        )
        self.assertTrue(eligible_nightly_connections(payload).filter(pk=self.connection.pk).exists())
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            import_status=HistoricalImportStatus.PARTIAL,
        )
        self.assertTrue(eligible_nightly_connections(payload).filter(pk=self.connection.pk).exists())
        WearableConnection.objects.filter(pk=self.connection.pk).update(synced_through=now)
        self.assertFalse(eligible_nightly_connections(payload).filter(pk=self.connection.pk).exists())

    def test_terminal_failure_sets_completed_timestamp(self):
        job = RookOutbox.objects.create(
            customer_profile=self.profile, job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
            connection=self.connection,
            idempotency_key=f"refresh:{self.connection.pk}",
            status=HealthJobStatus.RUNNING,
            attempt_count=MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
            scheduled_at=timezone.now() - timedelta(hours=3),
        )
        fail_health_job(job, ValueError("terminal failure"))
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.FAILED)
        self.assertIsNotNone(job.completed_at)

    def test_expired_final_lease_records_completion_time(self):
        job = RookOutbox.objects.create(
            customer_profile=self.profile, job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
            connection=self.connection,
            idempotency_key=f"refresh-stale:{self.connection.pk}",
            status=HealthJobStatus.RUNNING,
            attempt_count=MAX_ROOK_AUTH_OUTBOX_ATTEMPTS,
            scheduled_at=timezone.now() - timedelta(hours=3),
            locked_at=timezone.now() - timedelta(hours=3),
        )
        self.assertEqual(reset_stale_health_jobs(), [job.pk])
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.FAILED)
        self.assertIsNotNone(job.completed_at)

    def test_authorization_none_job_rolls_back_all_transitions(self):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.connected_at = None
        self.connection.save(update_fields=[
            "status", "authorization_status", "connected_at", "updated_at",
        ])
        with patch(
            "wearables.services.connections.enqueue_or_reuse_fetch_rook_data_job",
            return_value=(None, False),
        ):
            with self.assertRaises(RookServiceError):
                authorization_confirmed(self.connection)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.PENDING)
        self.assertIsNone(self.connection.connected_at)
        self.assertFalse(WearableConnectionEvent.objects.filter(
            connection=self.connection, event_type="authorization_confirmed",
        ).exists())

    def test_authorization_job_exception_rolls_back_all_transitions(self):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save(update_fields=["status", "authorization_status", "updated_at"])
        with patch(
            "wearables.services.connections.enqueue_or_reuse_fetch_rook_data_job",
            side_effect=RuntimeError("queue write failed"),
        ):
            with self.assertRaisesRegex(RuntimeError, "queue write failed"):
                authorization_confirmed(self.connection)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.AUTHORIZING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.PENDING)
        self.assertFalse(WearableConnectionEvent.objects.filter(
            connection=self.connection, event_type="authorization_confirmed",
        ).exists())

    def test_reviewer_composite_indexes_present_in_model(self):
        names = {index.name for index in RookOutbox._meta.indexes}
        self.assertIn("w_hjob_profile_type_s_idx", names)
        self.assertIn("w_hjob_conn_type_c_idx", names)
