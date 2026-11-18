"""Regression tests for the twelve PR-review corrections.

Run with the project's Python 3.14 environment and staging PostgreSQL:
uv run python manage.py test wearables.tests.test_pr_review_12_fixes
"""
import ast
from datetime import date, datetime, timedelta, timezone as utc_timezone
from types import SimpleNamespace
from uuid import uuid4

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
    HealthDailySummary, RookOutbox, RookWebhookReceipt,
    WearableConsent, WearableConnection,
)
from wearables.services.connections import get_or_create_connection, save_connection_transition
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import (
    ingest_rook_document, rebuild_daily_summaries, remap_member_local_days,
)
from wearables.services.job_claims import (
    STALE_JOB_MINUTES,
    LostHealthJobLease,
    complete_health_job,
    heartbeat_health_job,
    reset_stale_health_jobs,
)
from wearables.services.recovery import save_recovery_outcome
from wearables.services.client import RookServiceError
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus,
    HealthDomain, HealthJobStatus, HealthJobType, PermissionStatus,
)


def numeric_contribution(value, instant, *, version=1):
    """One ROOK document's share of a daily summary row (see daily_contributions)."""
    number = float(value)
    return {
        "v": version, "u": "steps", "n": 1, "s": number, "mn": number, "mx": number,
        "lv": number, "at": instant.isoformat(), "ds": ["Garmin"], "cf": 1.0,
    }


class ReviewStaticContractsTests(SimpleTestCase):
    def test_rook_workers_use_outbox_commands_not_lease_supervisor(self):
        yaml_text = (settings.BASE_DIR / "infra/integrations.yaml").read_text()
        self.assertIn("rook_auth:", yaml_text)
        self.assertIn("rook_data_fetch:", yaml_text)
        self.assertIn("process_rook_auth_jobs", yaml_text)
        self.assertIn("process_rook_data_fetch_jobs", yaml_text)
        self.assertFalse((settings.BASE_DIR / "assets/scripts/process_rook_auth_jobs.sh").exists())
        self.assertFalse((settings.BASE_DIR / "assets/scripts/process_rook_data_fetch_jobs.sh").exists())
        self.assertFalse((settings.BASE_DIR / "assets/scripts/process_pending_rook_sync_scan.sh").exists())
        self.assertFalse((settings.BASE_DIR / "assets/scripts/process_health_regular.sh").exists())
        self.assertFalse((settings.BASE_DIR / "wearables/management/commands/process_health_jobs.py").exists())
        self.assertFalse((settings.BASE_DIR / "wearables/management/commands/run_scheduled_worker.py").exists())

    def test_migration_does_not_import_live_enums(self):
        migration = (settings.BASE_DIR / "wearables/migrations/0001_initial.py").read_text()
        tree = ast.parse(migration)
        self.assertFalse(any(
            isinstance(node, ast.ImportFrom) and node.module == "wearables.utils.constants"
            for node in tree.body
        ))
        self.assertIn("FROZEN_WEARABLESOURCE_CHOICES", migration)
        self.assertIn("default='wearables-v1.2'", migration)

    def test_wearable_modules_have_no_raw_sql_or_inner_imports(self):
        for path in (settings.BASE_DIR / "wearables/services").glob("*.py"):
            contents = path.read_text()
            for raw_operation in (".raw(", "RawSQL(", "cursor.execute("):
                self.assertNotIn(raw_operation, contents, str(path))
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
    def test_stale_job_reclaim_window_is_bounded_and_does_not_expand_with_provider_timeout(self):
        self.assertEqual(STALE_JOB_MINUTES, 15)


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
        self.assertEqual(
            RookWebhookReceipt.objects.exclude(document_identity="").values("document_identity").distinct().count(),
            1,
        )
        latest = RookWebhookReceipt.objects.filter(status="processed").order_by("-document_version").first()
        self.assertEqual(latest.document_version, 2)

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
        with self.assertRaises(RookServiceError):
            save_recovery_outcome(stale, fields=["status"])
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.status, ConnectionStatus.DISCONNECTED)

    def test_daily_aggregates_do_not_make_one_query_per_metric(self):
        day = date(2026, 10, 8)
        instant = datetime(2026, 10, 8, 10, 0, tzinfo=utc_timezone.utc)
        for index in range(12):
            HealthDailySummary.objects.create(
                customer_profile=self.profile, domain=HealthDomain.ACTIVITY,
                metric=f"test_metric_{index}", local_date=day, source_key="Garmin",
                unit="steps", contributions={"review-doc": numeric_contribution(index, instant)},
            )
        # Stale aggregates prove the rebuild recomputes them from the stored entries.
        HealthDailySummary.objects.filter(metric="test_metric_5").update(latest=None, count=0)
        with CaptureQueriesContext(connection) as queries:
            rebuild_daily_summaries(
                customer_profile=self.profile, local_date=day,
                domains={HealthDomain.ACTIVITY},
            )
        # BEGIN/COMMIT and UPDATE statements are not N+1 reads.
        selects = [entry["sql"] for entry in queries
                   if entry["sql"].lstrip().upper().startswith("SELECT")]
        self.assertLessEqual(len(selects), 2, selects)
        self.assertEqual(HealthDailySummary.objects.filter(customer_profile=self.profile).count(), 12)
        self.assertEqual(HealthDailySummary.objects.filter(metric="test_metric_5").first().latest, 5.0)

    def test_abandoned_recovery_and_regular_jobs_both_fail_after_deadline(self):
        now = timezone.now()
        recovery = RookOutbox.objects.create(
            idempotency_key="review-recovery", job_type=HealthJobType.FETCH_ROOK_DATA,
            status=HealthJobStatus.RUNNING, scheduled_at=now,
            locked_at=now - timedelta(minutes=20), attempt_count=1,
        )
        ordinary = RookOutbox.objects.create(
            idempotency_key="review-revoke", job_type=HealthJobType.REVOKE_ROOK_CONNECTION,
            status=HealthJobStatus.RUNNING, scheduled_at=now,
            locked_at=now - timedelta(minutes=20), attempt_count=1,
        )
        reset_stale_health_jobs()
        recovery.refresh_from_db()
        ordinary.refresh_from_db()
        self.assertEqual(recovery.status, HealthJobStatus.FAILED)
        self.assertEqual(ordinary.status, HealthJobStatus.FAILED)
        with self.assertRaises(LostHealthJobLease):
            heartbeat_health_job(recovery)

    def test_previous_worker_attempt_cannot_complete_new_claim(self):
        job = RookOutbox.objects.create(
            idempotency_key="review-stale-attempt", job_type=HealthJobType.FETCH_ROOK_DATA,
            status=HealthJobStatus.RUNNING, scheduled_at=timezone.now(),
            locked_at=timezone.now(), attempt_count=1,
        )
        RookOutbox.objects.filter(pk=job.pk).update(attempt_count=2)
        complete_health_job(job, {"incorrect": True})
        job.refresh_from_db()
        self.assertEqual(job.status, HealthJobStatus.RUNNING)
        self.assertNotIn("incorrect", job.payload)

    def test_remap_moves_every_document_entry_and_keeps_utc_instants(self):
        instant = datetime(2026, 10, 8, 23, 30, tzinfo=utc_timezone.utc)
        HealthDailySummary.objects.create(
            customer_profile=self.profile, domain=HealthDomain.ACTIVITY, metric="steps",
            local_date=date(2026, 10, 8), source_key="Garmin", unit="steps",
            contributions={
                f"review-timezone-{index}": numeric_contribution(index, instant)
                for index in range(510)
            },
        )
        self.identity.timezone_name = "Asia/Kolkata"
        self.identity.save(update_fields=["timezone_name", "updated_at"])
        result = remap_member_local_days(self.profile)
        self.assertEqual(result["remapped"], 510)
        moved = HealthDailySummary.objects.get(local_date=date(2026, 10, 9), metric="steps")
        self.assertEqual(moved.count, 510)
        self.assertEqual(len(moved.contributions), 510)
        self.assertEqual(moved.last_observed_at, instant)
        self.assertFalse(HealthDailySummary.objects.filter(local_date=date(2026, 10, 8)).exists())

    def test_missing_document_normalize_does_not_advance_connection_sync(self):
        original_last_sync = timezone.localtime() - timedelta(days=3)
        WearableConnection.objects.filter(pk=self.connection.pk).update(
            last_data_processed_at=original_last_sync,
            last_successful_sync=original_last_sync,
        )
        from wearables.services.ingestion import normalize_health_document
        with self.assertRaisesMessage(ValueError, "Health document no longer exists."):
            normalize_health_document(uuid4())
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.last_data_processed_at, original_last_sync)
        self.assertEqual(self.connection.last_successful_sync, original_last_sync)
