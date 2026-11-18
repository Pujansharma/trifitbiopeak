"""Regression tests for PR #143: bounded freshness and shared recovery claims.

Run with Python 3.14 and a PostgreSQL test database. No ROOK calls needed.
"""
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.models import WearableConsent, RookOutbox, WearableConnection
from wearables.services.connections import authorization_confirmed, get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.scheduling import run_rook_sync_scan
from wearables.services.job_queue import enqueue_or_reuse_fetch_rook_data_job
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus, HealthJobStatus, HealthJobType,
    HistoricalImportStatus,
)


class QueueCoalescingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr143-queue@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        self.customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=self.customer, first_name="Queue", last_name="Tester", is_main=True,
        )
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=self.user, status=ConsentStatus.GRANTED,
            version="v1", granted_at=timezone.now(),
        )
        self.identity = get_or_create_rook_identity(self.profile)
        self.connection = get_or_create_connection(
            customer_profile=self.profile, identity=self.identity,
            data_source="Garmin", historical_days_requested=7,
        )
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            last_successful_sync=timezone.now(),
            import_status=HistoricalImportStatus.COMPLETED,
        )
        self.connection.refresh_from_db()

    @patch("wearables.services.job_queue.schedule_job_wake")
    def test_nightly_scan_enqueues_only_fetch_jobs(self, schedule_wake):
        now = timezone.now()
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            synced_through=now - timedelta(days=8),
        )
        first_scan = run_rook_sync_scan(now=now)
        second_scan = run_rook_sync_scan(now=now)
        self.assertEqual(first_scan["enqueuedCount"], 1)
        self.assertEqual(second_scan["enqueuedCount"], 0)
        self.assertEqual(RookOutbox.objects.filter(
            customer_profile=self.profile,
            job_type=HealthJobType.FETCH_ROOK_DATA,
        ).count(), 1)
        self.assertFalse(RookOutbox.objects.filter(job_type="freshness_check").exists())
        schedule_wake.assert_called()

    def test_one_open_recovery_and_hourly_cooldown_enforced_by_queue(self):
        self.connection.last_successful_sync = None
        self.connection.save(update_fields=["last_successful_sync", "updated_at"])
        job, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        reused, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertFalse(created)
        self.assertEqual(reused.pk, job.pk)
        RookOutbox.objects.filter(pk=job.pk).update(
            status=HealthJobStatus.COMPLETED, completed_at=timezone.now(),
        )
        recent, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertFalse(created)
        self.assertIsNone(recent)
        RookOutbox.objects.filter(pk=job.pk).update(
            completed_at=timezone.now() - timedelta(hours=2),
        )
        replacement, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        self.assertNotEqual(replacement.pk, job.pk)
        self.assertEqual(replacement.status, HealthJobStatus.PENDING)

    @patch("wearables.services.job_queue.enqueue_health_job")
    def test_authorization_reuses_inflight_recovery_without_changing_import_start(self, enqueue):
        # Existing RUNNING job owns the import-start generation. A second
        # authorization confirmation must not cause an overlapping ROOK pull.
        started = timezone.now() - timedelta(minutes=8)
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.import_started_at = started
        self.connection.save(update_fields=[
            "status", "authorization_status", "import_started_at", "updated_at",
        ])
        job = RookOutbox.objects.create(
            job_type=HealthJobType.FETCH_ROOK_DATA,
            customer_profile=self.profile, connection=self.connection,
            idempotency_key="existing-inflight-recovery", status=HealthJobStatus.RUNNING,
            attempt_count=1, scheduled_at=started, started_at=started, locked_at=started,
        )
        authorization_confirmed(self.connection)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.import_started_at, started)
        self.assertEqual(self.connection.status, ConnectionStatus.IMPORTING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.AUTHORIZED)
        self.assertEqual(RookOutbox.objects.filter(
            connection=self.connection, job_type=HealthJobType.FETCH_ROOK_DATA,
        ).count(), 1)
        self.assertTrue(RookOutbox.objects.filter(pk=job.pk).exists())
        enqueue.assert_not_called()

    @patch("wearables.services.job_queue.enqueue_health_job")
    def test_authorization_does_not_append_recovery_when_pending_exists(self, enqueue):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save(update_fields=["status", "authorization_status", "updated_at"])
        RookOutbox.objects.create(
            job_type=HealthJobType.FETCH_ROOK_DATA,
            customer_profile=self.profile, connection=self.connection,
            idempotency_key="pending-import", status=HealthJobStatus.PENDING,
            scheduled_at=timezone.now(),
        )
        authorization_confirmed(self.connection)
        self.assertEqual(RookOutbox.objects.filter(
            connection=self.connection, job_type=HealthJobType.FETCH_ROOK_DATA,
        ).count(), 1)
        enqueue.assert_not_called()


class CacheReadinessTests(SimpleTestCase):
    @override_settings(
        SETTINGS_MODULE="core.settings.production",
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "health": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        },
    )
    def test_production_local_memory_throttling_warns_about_per_worker_limits(self):
        results = rook_readiness_checks()
        self.assertTrue(any(
            severity == "WARN" and name == "WEARABLE_EDGE_RATE_LIMIT"
            for severity, name, _ in results
        ))


class RookWakeQueueReadinessTests(SimpleTestCase):
    @override_settings(
        SETTINGS_MODULE="core.settings.production",
        ROOK_API_REQUESTS_PER_MINUTE=60, ROOK_API_REQUESTS_PER_DAY=1000,
        ROOK_AUTH_OUTBOX_QUEUE_URL="", ROOK_DATA_FETCH_OUTBOX_QUEUE_URL="",
    )
    def test_production_missing_both_wake_urls_fails_readiness(self):
        errors = {name for severity, name, _ in rook_readiness_checks() if severity == "ERROR"}
        self.assertIn("ROOK_AUTH_OUTBOX_QUEUE_URL", errors)
        self.assertIn("ROOK_DATA_FETCH_OUTBOX_QUEUE_URL", errors)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        ROOK_API_REQUESTS_PER_MINUTE=60, ROOK_API_REQUESTS_PER_DAY=1000,
        ROOK_AUTH_OUTBOX_QUEUE_URL="https://sqs.ap-south-1.amazonaws.com/123/health",
        ROOK_DATA_FETCH_OUTBOX_QUEUE_URL="https://sqs.ap-south-1.amazonaws.com/123/recovery",
    )
    def test_staging_valid_wake_urls_pass_readiness(self):
        errors = {name for severity, name, _ in rook_readiness_checks() if severity == "ERROR"}
        self.assertNotIn("ROOK_AUTH_OUTBOX_QUEUE_URL", errors)
        self.assertNotIn("ROOK_DATA_FETCH_OUTBOX_QUEUE_URL", errors)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        ROOK_AUTH_OUTBOX_QUEUE_URL="http://sqs.example.invalid/health",
        ROOK_DATA_FETCH_OUTBOX_QUEUE_URL="   ",
    )
    def test_invalid_wake_urls_fail_readiness(self):
        errors = {name for severity, name, _ in rook_readiness_checks() if severity == "ERROR"}
        self.assertIn("ROOK_AUTH_OUTBOX_QUEUE_URL", errors)
        self.assertIn("ROOK_DATA_FETCH_OUTBOX_QUEUE_URL", errors)
