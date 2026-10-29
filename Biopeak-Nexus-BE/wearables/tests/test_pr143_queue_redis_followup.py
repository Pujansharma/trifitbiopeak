"""Regression tests for PR #143: bounded freshness and shared recovery claims.

Run with Python 3.14 and a PostgreSQL test database. No ROOK calls needed.
"""
from datetime import timedelta
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.models import HealthProcessingJob, WearableConnection
from wearables.services.connections import authorization_confirmed, get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.job_processor import connections_requiring_recovery_pull
from wearables.services.job_queue import (
    enqueue_or_reuse_freshness_job, enqueue_or_reuse_recovery_job,
)
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, HealthJobStatus, HealthJobType,
    HistoricalImportStatus, HEALTH_MAXIMUM_JOB_ATTEMPTS,
)


class QueueCoalescingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr143-queue@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        self.customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=self.customer, first_name="Queue", last_name="Tester", is_main=True,
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

    def test_hourly_sweeps_do_not_stack_open_jobs_or_accumulate_completed_rows(self):
        call_command("enqueue_health_freshness_checks", verbosity=0)
        call_command("enqueue_health_freshness_checks", verbosity=0)
        jobs = HealthProcessingJob.objects.filter(
            customer_profile=self.profile, job_type=HealthJobType.FRESHNESS_CHECK,
        )
        self.assertEqual(jobs.count(), 1)
        job = jobs.first()
        self.assertEqual(job.idempotency_key, f"freshness:{self.profile.pk}")
        HealthProcessingJob.objects.filter(pk=job.pk).update(
            status=HealthJobStatus.COMPLETED, attempt_count=2,
        )
        call_command("enqueue_health_freshness_checks", verbosity=0)
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.COMPLETED)
        HealthProcessingJob.objects.filter(pk=job.pk).update(
            scheduled_at=timezone.now() - timedelta(hours=2),
        )
        call_command("enqueue_health_freshness_checks", verbosity=0)
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.PENDING)
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(jobs.count(), 1)

    def test_scheduler_limits_new_work_and_fairly_reaches_other_profiles(self):
        for number in range(4):
            user = User.objects.create_user(email=f"pr143-fairness-{number}@example.com")
            UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
            customer = Customer.objects.create(user=user)
            profile = CustomerProfile.objects.create(
                customer=customer, first_name="Fair", last_name=f"Number {number}",
                is_main=True,
            )
            identity = get_or_create_rook_identity(profile)
            connection = get_or_create_connection(
                customer_profile=profile, identity=identity,
                data_source="Garmin", historical_days_requested=7,
            )
            WearableConnection.objects.filter(pk=connection.pk).update(
                status=ConnectionStatus.ACTIVE,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                last_successful_sync=timezone.now(),
                import_status=HistoricalImportStatus.COMPLETED,
            )
        for expected in (2, 4, 5):
            call_command("enqueue_health_freshness_checks", freshness_limit=2, verbosity=0)
            self.assertEqual(HealthProcessingJob.objects.filter(
                job_type=HealthJobType.FRESHNESS_CHECK,
            ).count(), expected)
        call_command("enqueue_health_freshness_checks", freshness_limit=2, verbosity=0)
        self.assertEqual(HealthProcessingJob.objects.filter(
            job_type=HealthJobType.FRESHNESS_CHECK,
        ).count(), 5)

    def test_legacy_pending_hourly_key_prevents_new_fixed_key(self):
        old = HealthProcessingJob.objects.create(
            customer_profile=self.profile, job_type=HealthJobType.FRESHNESS_CHECK,
            idempotency_key=f"freshness:{self.profile.pk}:legacy-hour",
            status=HealthJobStatus.PENDING, scheduled_at=timezone.now() - timedelta(hours=2),
        )
        new_job, created = enqueue_or_reuse_freshness_job(customer_profile=self.profile)
        self.assertFalse(created)
        self.assertEqual(new_job.pk, old.pk)
        self.assertEqual(HealthProcessingJob.objects.filter(
            job_type=HealthJobType.FRESHNESS_CHECK,
            customer_profile=self.profile,
        ).count(), 1)

    def test_retryable_failed_freshness_job_is_not_requeued(self):
        job = HealthProcessingJob.objects.create(
            customer_profile=self.profile, job_type=HealthJobType.FRESHNESS_CHECK,
            idempotency_key=f"freshness:{self.profile.pk}",
            status=HealthJobStatus.FAILED, attempt_count=1,
            scheduled_at=timezone.now() + timedelta(minutes=30),
        )
        same, created = enqueue_or_reuse_freshness_job(customer_profile=self.profile)
        self.assertFalse(created)
        self.assertEqual(same.pk, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.attempt_count, 1)

    def test_exhausted_freshness_job_can_recover_after_hour(self):
        job = HealthProcessingJob.objects.create(
            customer_profile=self.profile, job_type=HealthJobType.FRESHNESS_CHECK,
            idempotency_key=f"freshness:{self.profile.pk}",
            status=HealthJobStatus.FAILED,
            attempt_count=HEALTH_MAXIMUM_JOB_ATTEMPTS,
            scheduled_at=timezone.now() - timedelta(hours=2),
        )
        same, queued = enqueue_or_reuse_freshness_job(customer_profile=self.profile)
        self.assertTrue(queued)
        self.assertEqual(same.pk, job.pk)
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.PENDING)
        self.assertEqual(job.attempt_count, 0)

    def test_one_open_recovery_and_hourly_cooldown_are_filtered_at_database_level(self):
        self.connection.last_successful_sync = None
        self.connection.save(update_fields=["last_successful_sync", "updated_at"])
        self.assertIn(self.connection.pk, list(connections_requiring_recovery_pull().values_list("pk", flat=True)))
        job, created = enqueue_or_reuse_recovery_job(
            connection=self.connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        self.assertFalse(connections_requiring_recovery_pull().filter(pk=self.connection.pk).exists())
        HealthProcessingJob.objects.filter(pk=job.pk).update(status=HealthJobStatus.COMPLETED)
        self.assertFalse(connections_requiring_recovery_pull().filter(pk=self.connection.pk).exists())
        HealthProcessingJob.objects.filter(pk=job.pk).update(
            created_at=timezone.now() - timedelta(hours=2),
        )
        self.assertTrue(connections_requiring_recovery_pull().filter(pk=self.connection.pk).exists())

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
        job = HealthProcessingJob.objects.create(
            job_type=HealthJobType.RECOVERY_PULL,
            customer_profile=self.profile, connection=self.connection,
            idempotency_key="existing-inflight-recovery", status=HealthJobStatus.RUNNING,
            attempt_count=1, scheduled_at=started, started_at=started, locked_at=started,
        )
        authorization_confirmed(self.connection)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.import_started_at, started)
        self.assertEqual(self.connection.status, ConnectionStatus.IMPORTING)
        self.assertEqual(self.connection.authorization_status, AuthorizationStatus.AUTHORIZED)
        self.assertEqual(HealthProcessingJob.objects.filter(
            connection=self.connection, job_type=HealthJobType.RECOVERY_PULL,
        ).count(), 1)
        self.assertTrue(HealthProcessingJob.objects.filter(pk=job.pk).exists())
        enqueue.assert_not_called()

    @patch("wearables.services.job_queue.enqueue_health_job")
    def test_authorization_does_not_append_recovery_when_pending_exists(self, enqueue):
        self.connection.status = ConnectionStatus.AUTHORIZING
        self.connection.authorization_status = AuthorizationStatus.PENDING
        self.connection.save(update_fields=["status", "authorization_status", "updated_at"])
        HealthProcessingJob.objects.create(
            job_type=HealthJobType.RECOVERY_PULL,
            customer_profile=self.profile, connection=self.connection,
            idempotency_key="pending-import", status=HealthJobStatus.PENDING,
            scheduled_at=timezone.now(),
        )
        authorization_confirmed(self.connection)
        self.assertEqual(HealthProcessingJob.objects.filter(
            connection=self.connection, job_type=HealthJobType.RECOVERY_PULL,
        ).count(), 1)
        enqueue.assert_not_called()


class CacheReadinessTests(SimpleTestCase):
    @override_settings(
        WEARABLES_ENABLED=True, SETTINGS_MODULE="core.settings.production",
        CACHES={
            "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
            "health": {"BACKEND": "django.core.cache.backends.dummy.DummyCache"},
        },
    )
    def test_production_local_memory_throttling_is_a_blocking_error(self):
        results = rook_readiness_checks()
        self.assertTrue(any(
            severity == "ERROR" and name == "WEARABLE_EDGE_RATE_LIMIT"
            for severity, name, _ in results
        ))
