"""Follow-up regression tests for the four P1 comments on PR #143.

Run using Python 3.14 with the project's Django/PostgreSQL test database:
uv run python manage.py test wearables.tests.test_pr143_followup_fixes
"""
from datetime import timedelta
from functools import partial
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.db import connection as database_connection
from django.test import SimpleTestCase, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import HealthProcessingJob, WearableConnection, WearableConnectionEvent
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.serializers import TimelineQuerySerializer
from wearables.services.client import RookServiceError, validate_authorization_url
from wearables.services.connections import get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.job_processor import process_pending_health_jobs
from wearables.services.job_queue import enqueue_or_reuse_recovery_job
from wearables.services.oauth import callback_url_for_connection, complete_oauth_callback
from wearables.services.timeline import timeline_payload
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, HealthJobStatus, HealthJobType,
    HEALTH_TIMELINE_MAXIMUM_LIMIT, HEALTH_TIMELINE_MAXIMUM_OFFSET,
)


def collect_rook_transaction_state(*, rook_user_id: str, results: list[bool]) -> set[str]:
    results.append(database_connection.in_atomic_block)
    return {"Garmin"}



class HostAndTimelineLimitTests(SimpleTestCase):
    @override_settings(ROOK_AUTHORIZATION_ALLOWED_HOSTS=[])
    def test_missing_authorization_allowlist_rejects_garmin_and_other_providers(self):
        for provider, url in (
            ("Garmin", "https://connect.garmin.com/oauthConfirm"),
            ("Fitbit", "https://valid-provider.example/authorize"),
        ):
            with self.subTest(provider=provider):
                with self.assertRaisesRegex(RookServiceError, "untrusted authorization host"):
                    validate_authorization_url(provider, url)

    @override_settings(ROOK_AUTHORIZATION_ALLOWED_HOSTS=None)
    def test_unset_authorization_allowlist_is_also_rejected(self):
        with self.assertRaises(RookServiceError):
            validate_authorization_url("Garmin", "https://connect.garmin.com/oauthConfirm")

    @override_settings(ROOK_PROVISIONED_SOURCES="Garmin", ROOK_AUTHORIZATION_ALLOWED_HOSTS=[])
    def test_configuration_check_reports_missing_trusted_hosts(self):
        self.assertIn("ROOK_AUTHORIZATION_ALLOWED_HOSTS", {
            key for severity, key, _ in rook_readiness_checks() if severity == "ERROR"
        })

    @override_settings(ROOK_AUTHORIZATION_ALLOWED_HOSTS=["valid-provider.example", "connect.garmin.com"])
    def test_only_explicit_trusted_hosts_are_allowed(self):
        self.assertEqual(
            validate_authorization_url("Fitbit", "https://valid-provider.example/authorize"),
            "https://valid-provider.example/authorize",
        )
        self.assertEqual(
            validate_authorization_url("Garmin", "https://connect.garmin.com/oauthConfirm"),
            "https://connect.garmin.com/oauthConfirm",
        )
        for url in (
            "https://untrusted.example/authorize",
            "https://valid-provider.example.evil.example/authorize",
            "http://valid-provider.example/authorize",
            "https://valid-provider.example:8443/authorize",
        ):
            with self.subTest(url=url):
                with self.assertRaises(RookServiceError):
                    validate_authorization_url("Fitbit", url)
        with self.assertRaises(RookServiceError):
            validate_authorization_url("Garmin", "https://valid-provider.example/authorize")

    def test_timeline_offset_boundary_is_validated(self):
        self.assertTrue(TimelineQuerySerializer(data={"offset": HEALTH_TIMELINE_MAXIMUM_OFFSET}).is_valid())
        serializer = TimelineQuerySerializer(data={"offset": HEALTH_TIMELINE_MAXIMUM_OFFSET + 1})
        self.assertFalse(serializer.is_valid())
        self.assertIn("offset", serializer.errors)

    def test_timeline_service_rejects_unbounded_offsets_and_limits(self):
        parameters = {
            "customer_profile": SimpleNamespace(), "start_date": None,
            "end_date": None, "domain": "heart", "offset": 0, "limit": 50,
        }
        with self.assertRaises(ValueError):
            timeline_payload(**{**parameters, "offset": HEALTH_TIMELINE_MAXIMUM_OFFSET + 1})
        with self.assertRaises(ValueError):
            timeline_payload(**{**parameters, "limit": HEALTH_TIMELINE_MAXIMUM_LIMIT + 1})

    @override_settings(TIMELINE_INCLUDE_LEGACY_RESULTS=True)
    @patch("wearables.services.timeline._timeline_gaps", return_value=[])
    @patch("wearables.services.timeline._clinical_entries", return_value=[])
    @patch("wearables.services.timeline._wearable_entries", return_value=[])
    def test_maximum_allowed_page_still_uses_bounded_queryset_slices(self, wearables, clinical, gaps):
        maximum = HEALTH_TIMELINE_MAXIMUM_OFFSET + HEALTH_TIMELINE_MAXIMUM_LIMIT + 1
        timeline_payload(
            customer_profile=SimpleNamespace(rook_identity=None), start_date=None,
            end_date=None, domain=None, offset=HEALTH_TIMELINE_MAXIMUM_OFFSET,
            limit=HEALTH_TIMELINE_MAXIMUM_LIMIT,
        )
        self.assertEqual(wearables.call_args.kwargs["maximum"], maximum)
        self.assertEqual(clinical.call_args.kwargs["maximum"], maximum)


class FollowupJobTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr143-followup@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        self.customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=self.customer, first_name="Review", last_name="Followup", is_main=True,
        )
        identity = get_or_create_rook_identity(self.profile, timezone_name="UTC")
        self.provider_connection = get_or_create_connection(
            customer_profile=self.profile, identity=identity, data_source="Garmin",
            historical_days_requested=7,
        )
        WearableConnection.objects.filter(pk=self.provider_connection.pk).update(
            status=ConnectionStatus.ACTIVE, authorization_status=AuthorizationStatus.AUTHORIZED,
        )
        self.provider_connection.refresh_from_db()

    def add_job(self, job_type, key, offset_minutes):
        return HealthProcessingJob.objects.create(
            job_type=job_type, idempotency_key=key, customer_profile=self.profile,
            connection=self.provider_connection if job_type == HealthJobType.RECOVERY_PULL else None,
            scheduled_at=timezone.now() - timedelta(minutes=offset_minutes),
        )

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_normalization_runs_first_and_only_one_recovery_per_sweep(self, processor):
        recoveries = [self.add_job(HealthJobType.RECOVERY_PULL, f"old-recovery-{index}", 30) for index in range(4)]
        freshness = self.add_job(HealthJobType.FRESHNESS_CHECK, "old-freshness", 20)
        normalize = self.add_job(HealthJobType.NORMALIZE_DOCUMENT, "new-normalize", 1)

        result = process_pending_health_jobs(limit=10)
        processed_ids = [item["jobId"] for item in result]
        self.assertEqual(processed_ids[0], str(normalize.pk))
        self.assertEqual(processed_ids[1], str(freshness.pk))
        self.assertEqual(len(result), 3)
        self.assertEqual(len(set(processed_ids).intersection(str(job.pk) for job in recoveries)), 1)
        self.assertEqual(HealthProcessingJob.objects.filter(
            job_type=HealthJobType.RECOVERY_PULL, status=HealthJobStatus.PENDING,
        ).count(), 3)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_recovery_has_reserved_slot_when_freshness_backlog_exceeds_sweep_limit(self, processor):
        normalize = self.add_job(HealthJobType.NORMALIZE_DOCUMENT, "incoming-normalize", 1)
        recovery = self.add_job(HealthJobType.RECOVERY_PULL, "awaiting-recovery", 30)
        for index in range(55):
            self.add_job(HealthJobType.FRESHNESS_CHECK, f"hourly-freshness-{index}", 40)

        results = process_pending_health_jobs(limit=50)
        processed_ids = [item["jobId"] for item in results]
        self.assertEqual(len(results), 50)
        self.assertEqual(processed_ids[0], str(normalize.pk))
        self.assertIn(str(recovery.pk), processed_ids)
        self.assertEqual(processed_ids.count(str(recovery.pk)), 1)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_full_normalization_queue_never_yields_slot_to_slow_recovery(self, processor):
        recovery = self.add_job(HealthJobType.RECOVERY_PULL, "waiting-recovery", 30)
        for index in range(51):
            self.add_job(HealthJobType.NORMALIZE_DOCUMENT, f"normalization-{index}", 1)

        results = process_pending_health_jobs(limit=50)
        processed_ids = [item["jobId"] for item in results]
        self.assertEqual(len(results), 50)
        self.assertNotIn(str(recovery.pk), processed_ids)
        self.assertEqual(HealthProcessingJob.objects.filter(
            job_type=HealthJobType.NORMALIZE_DOCUMENT,
            status=HealthJobStatus.PENDING,
        ).count(), 1)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_recovery_is_not_starved_when_only_recovery_jobs_exist(self, processor):
        self.add_job(HealthJobType.RECOVERY_PULL, "recovery-only", 30)
        result = process_pending_health_jobs(limit=50)
        self.assertEqual(len(result), 1)

    def test_manual_retry_reuses_open_job_and_creates_new_after_completion(self):
        first, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertTrue(created)
        second, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        third, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertFalse(created)
        self.assertEqual(third.pk, first.pk)
        self.assertEqual(HealthProcessingJob.objects.filter(
            connection=self.provider_connection, job_type=HealthJobType.RECOVERY_PULL,
        ).count(), 1)

        HealthProcessingJob.objects.filter(pk=first.pk).update(status=HealthJobStatus.COMPLETED)
        later, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertTrue(created)
        self.assertNotEqual(later.pk, first.pk)

    def test_scheduler_respects_hourly_recovery_cooldown(self):
        first, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        HealthProcessingJob.objects.filter(pk=first.pk).update(status=HealthJobStatus.COMPLETED)
        another, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertIsNone(another)
        self.assertFalse(created)
        self.assertEqual(HealthProcessingJob.objects.filter(
            connection=self.provider_connection, job_type=HealthJobType.RECOVERY_PULL,
        ).count(), 1)

    def test_manual_retry_expedites_failed_recovery_without_creating_duplicates(self):
        first, _ = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        later = timezone.now() + timedelta(hours=1)
        HealthProcessingJob.objects.filter(pk=first.pk).update(
            status=HealthJobStatus.FAILED, scheduled_at=later, attempt_count=1,
        )
        reused, created = enqueue_or_reuse_recovery_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        reused.refresh_from_db()
        self.assertFalse(created)
        self.assertEqual(reused.pk, first.pk)
        self.assertLess(reused.scheduled_at, later)


class OAuthTransactionBoundaryTests(TransactionTestCase):
    @override_settings(ROOK_CLIENT_UUID="review-client", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.oauth.RookClient")
    def test_external_rook_authorization_check_runs_before_atomic_block(self, client_class):
        user = User.objects.create_user(email="pr143-oauth@example.com")
        UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=user)
        profile = CustomerProfile.objects.create(
            customer=customer, first_name="Callback", last_name="Test", is_main=True,
        )
        identity = get_or_create_rook_identity(profile, timezone_name="UTC")
        connection = get_or_create_connection(
            customer_profile=profile, identity=identity,
            data_source="Garmin", historical_days_requested=7,
        )
        WearableConnection.objects.filter(pk=connection.pk).update(
            status=ConnectionStatus.AUTHORIZING, authorization_status=AuthorizationStatus.PENDING,
        )
        connection.refresh_from_db()
        callback = callback_url_for_connection(
            connection, actor_user=user, previous_status=ConnectionStatus.NEVER_CONNECTED,
        )
        transaction_state_during_rook_call = []

        client_class.return_value.get_authorized_sources.side_effect = partial(
            collect_rook_transaction_state, results=transaction_state_during_rook_call,
        )
        result = complete_oauth_callback(
            urlsplit(callback).path.rsplit("/", 1)[-1],
            rook_client_uuid="review-client", rook_user_id=identity.rook_user_id,
        )
        self.assertEqual(result, "authorized")
        self.assertEqual(transaction_state_during_rook_call, [False])
        self.assertTrue(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_verified",
        ).exists())
