"""Regression tests for the twelve PR-review corrections.

Run with the project's Python 3.14 environment and staging PostgreSQL:
uv run python manage.py test wearables.tests.test_pr_review_12_fixes
"""
import ast
from datetime import date, datetime, timedelta, timezone as utc_timezone

from django.conf import settings
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import (
    HealthDailySummary, HealthObservation, HealthProcessingJob, RookHealthDocument,
    WearableConsent, WearableConnection,
)
from wearables.services.connections import get_or_create_connection, save_connection_transition
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import (
    ingest_rook_document, rebuild_daily_summaries, remap_member_local_days,
)
from wearables.services.job_processor import (
    complete_health_job, heartbeat_health_job, recovery_lease_minutes,
    reset_stale_health_jobs, save_recovery_outcome,
)
from wearables.services.client import RookServiceError
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus,
    HealthDomain, HealthJobStatus, HealthJobType, PermissionStatus,
)


class ReviewStaticContractsTests(SimpleTestCase):
    def test_sweep_schedules_both_health_commands(self):
        script = (settings.BASE_DIR / "assets/scripts/sweep_jobs.sh").read_text()
        self.assertIn("enqueue_health_freshness_checks", script)
        self.assertIn("process_health_jobs --limit", script)

    def test_migration_does_not_import_live_enums(self):
        migration = (settings.BASE_DIR / "wearables/migrations/0001_initial.py").read_text()
        tree = ast.parse(migration)
        self.assertFalse(any(
            isinstance(node, ast.ImportFrom) and node.module == "wearables.utils.constants"
            for node in tree.body
        ))
        self.assertIn("FROZEN_WEARABLESOURCE_CHOICES", migration)
        self.assertIn("default='wearables-v1.2'", migration)

    def test_wearable_modules_have_no_row_locks_or_inner_imports(self):
        for path in (settings.BASE_DIR / "wearables/services").glob("*.py"):
            contents = path.read_text()
            self.assertNotIn(".select_for_update()", contents, str(path))
            tree = ast.parse(contents)
            inner_imports = [
                node.lineno for node in ast.walk(tree)
                if isinstance(node, (ast.Import, ast.ImportFrom)) and node.col_offset > 0
            ]
            self.assertFalse(inner_imports, f"{path}: {inner_imports}")

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health", ROOK_SDK_CLIENT_UUID="native-uuid",
        ROOK_SDK_SECRET="same-secret", ROOK_SECRET_KEY="same-secret",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=True, ROOK_WEBHOOK_HASH_KEY="test-key",
        ROOK_BASE_URL="https://api.rook-connect.review",
    )
    def test_sdk_cannot_reuse_server_basic_auth_secret(self):
        checks = rook_readiness_checks()
        self.assertTrue(any(
            severity == "ERROR" and name == "ROOK_SDK_SECRET"
            for severity, name, _ in checks
        ))

    @override_settings(
        ROOK_PROVISIONED_SOURCES="Apple Health", ROOK_SDK_CLIENT_UUID="native-uuid",
        ROOK_SDK_SECRET="native-dedicated", ROOK_SECRET_KEY="server-only",
        ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=False,
        ROOK_WEBHOOK_HASH_KEY="test-key", ROOK_BASE_URL="https://api.rook-connect.review",
    )
    def test_sdk_needs_explicit_mobile_distribution_approval(self):
        checks = rook_readiness_checks()
        self.assertTrue(any(
            severity == "ERROR" and name == "ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC"
            for severity, name, _ in checks
        ))

    @override_settings(ROOK_READ_TIMEOUT_SECONDS=120, ROOK_CONNECT_TIMEOUT_SECONDS=20)
    def test_recovery_lease_exceeds_worst_case_network_duration(self):
        self.assertGreater(recovery_lease_minutes(), (21 * 140) / 60)


class ReviewDatabaseTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="review-fixes@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Review", last_name="Tests", is_main=True,
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
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            permission_status=PermissionStatus.GRANTED,
        )
        self.connection.refresh_from_db()

    def payload(self, *, version=1, steps=5000):
        return {
            "client_uuid": "review-test", "user_id": self.identity.rook_user_id,
            "datetime": "2026-10-08T10:00:00+00:00",
            "data_structure": "physical_health_summary", "document_version": version,
            "source_of_data_string": "Garmin", "accumulated_steps_int": steps,
        }

    def test_document_replay_and_version_correction_preserve_single_identity(self):
        first = ingest_rook_document(self.payload(), signature_valid=True)
        second = ingest_rook_document(self.payload(), signature_valid=True)
        updated = ingest_rook_document(self.payload(version=2, steps=7000), signature_valid=True)
        self.assertTrue(first["queued"])
        self.assertTrue(second["duplicate"])
        self.assertTrue(updated["queued"])
        self.assertEqual(RookHealthDocument.objects.count(), 1)
        self.assertEqual(RookHealthDocument.objects.first().document_version, 2)

    def test_stale_connection_object_cannot_override_disconnection(self):
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.AUTHORIZING,
            authorization_status=AuthorizationStatus.PENDING,
        )
        stale = WearableConnection.objects.filter(pk=self.connection.pk).first()
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.DISCONNECTED,
            authorization_status=AuthorizationStatus.REVOKED,
        )
        with self.assertRaisesRegex(ValueError, "concurrently"):
            save_connection_transition(
                stale, status=ConnectionStatus.IMPORTING,
                authorization_status=AuthorizationStatus.AUTHORIZED,
                event_type="stale_auth_callback",
            )
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)

    def test_long_recovery_cannot_reopen_disconnected_source(self):
        # The worker holds a previously authorized in-memory connection while
        # the member disconnects in another request/worker.
        stale = WearableConnection.objects.filter(pk=self.connection.pk).first()
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            status=ConnectionStatus.DISCONNECTED,
            authorization_status=AuthorizationStatus.REVOKED,
            disconnected_at=timezone.now(),
        )
        stale.status = ConnectionStatus.ACTIVE
        with self.assertRaisesRegex(RookServiceError, "authorization changed"):
            save_recovery_outcome(stale, fields=["status"])
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)

    def test_daily_aggregates_do_not_make_one_query_per_metric(self):
        incoming = ingest_rook_document(self.payload(), signature_valid=True,
                                        enqueue_normalization=False)
        document = RookHealthDocument.objects.filter(pk=incoming["documentId"]).first()
        day = date(2026, 10, 8)
        HealthObservation.objects.bulk_create([
            HealthObservation(
                customer_profile=self.profile, document=document, connection=self.connection,
                observation_identity=f"review-aggregation-{index}",
                domain=HealthDomain.ACTIVITY, metric=f"test_metric_{index}",
                field_path=f"measurement.{index}", observed_at=document.observed_at,
                local_date=day, numeric_value=float(index), unit="steps",
                source_key="Garmin", data_sources=["Garmin"],
            ) for index in range(12)
        ])
        with CaptureQueriesContext(connection) as queries:
            rebuild_daily_summaries(
                customer_profile=self.profile, local_date=day,
                domains={HealthDomain.ACTIVITY},
            )
        # BEGIN/COMMIT and INSERT statements are not N+1 reads.
        selects = [entry["sql"] for entry in queries
                   if entry["sql"].lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(selects), 2, selects)
        self.assertEqual(HealthDailySummary.objects.filter(customer_profile=self.profile).count(), 12)
        self.assertEqual(HealthDailySummary.objects.filter(metric="test_metric_5").first().latest, 5.0)

    def test_long_recovery_lease_does_not_expire_at_fifteen_minutes(self):
        now = timezone.now()
        recovery = HealthProcessingJob.objects.create(
            idempotency_key="review-recovery", job_type=HealthJobType.RECOVERY_PULL,
            status=HealthJobStatus.RUNNING, scheduled_at=now,
            locked_at=now - timedelta(minutes=20), attempt_count=1,
        )
        ordinary = HealthProcessingJob.objects.create(
            idempotency_key="review-normalize", job_type=HealthJobType.NORMALIZE_DOCUMENT,
            status=HealthJobStatus.RUNNING, scheduled_at=now,
            locked_at=now - timedelta(minutes=20), attempt_count=1,
        )
        reset_stale_health_jobs()
        recovery.refresh_from_db()
        ordinary.refresh_from_db()
        self.assertEqual(recovery.status, HealthJobStatus.RUNNING)
        self.assertEqual(ordinary.status, HealthJobStatus.FAILED)
        heartbeat_health_job(recovery)
        recovery.refresh_from_db()
        self.assertGreater(recovery.locked_at, now - timedelta(seconds=5))

    def test_previous_worker_attempt_cannot_complete_new_claim(self):
        job = HealthProcessingJob.objects.create(
            idempotency_key="review-stale-attempt", job_type=HealthJobType.RECOVERY_PULL,
            status=HealthJobStatus.RUNNING, scheduled_at=timezone.now(),
            locked_at=timezone.now(), attempt_count=1,
        )
        HealthProcessingJob.objects.filter(pk=job.pk).update(attempt_count=2)
        complete_health_job(job, {"incorrect": True})
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.RUNNING)
        self.assertNotIn("incorrect", job.payload)

    def test_remap_processes_multiple_batches_and_keeps_utc_instants(self):
        document_id = ingest_rook_document(
            self.payload(), signature_valid=True, enqueue_normalization=False,
        )["documentId"]
        document = RookHealthDocument.objects.filter(pk=document_id).first()
        instant = datetime(2026, 10, 8, 23, 30, tzinfo=utc_timezone.utc)
        HealthObservation.objects.bulk_create([
            HealthObservation(
                customer_profile=self.profile, document=document, connection=self.connection,
                observation_identity=f"review-timezone-{index}",
                domain=HealthDomain.ACTIVITY, metric="steps",
                field_path=f"steps.{index}", observed_at=instant,
                local_date=date(2026, 10, 8), numeric_value=float(index),
                unit="steps", source_key="Garmin", data_sources=["Garmin"],
            ) for index in range(510)
        ])
        self.identity.timezone_name = "Asia/Kolkata"
        self.identity.save(update_fields=["timezone_name", "updated_at"])
        result = remap_member_local_days(self.profile)
        self.assertEqual(result["remapped"], 510)
        self.assertEqual(HealthObservation.objects.filter(local_date=date(2026, 10, 9)).count(), 510)
        self.assertEqual(HealthObservation.objects.filter(observed_at=instant).count(), 510)
