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
from wearables.models import RookOutbox, WearableConnection, WearableConnectionEvent, WearableConsent
from wearables.management.commands.check_rook_configuration import rook_readiness_checks
from wearables.services.client import RookServiceError, validate_authorization_url
from wearables.services.connections import get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.job_processor import process_pending_rook_outbox
from wearables.services.wake import QUEUE_KIND_AUTH, QUEUE_KIND_DATA_FETCH
from wearables.services.job_queue import enqueue_or_reuse_fetch_rook_data_job
from wearables.services.oauth import callback_url_for_connection, complete_oauth_callback
from wearables.utils.constants import (
    AuthorizationStatus, ConnectionStatus, ConsentStatus, HealthJobStatus, HealthJobType,
)


def collect_rook_transaction_state(*, rook_user_id: str, results: list[bool]) -> set[str]:
    results.append(database_connection.in_atomic_block)
    return {"Garmin"}



class AuthorizationHostAllowlistTests(SimpleTestCase):
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



class FollowupJobTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="pr143-followup@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        self.customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=self.customer, first_name="Review", last_name="Followup", is_main=True,
        )
        WearableConsent.objects.create(
            customer_profile=self.profile, status=ConsentStatus.GRANTED,
            granted_by=self.user, granted_at=timezone.now(), version="v1",
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
        return RookOutbox.objects.create(
            job_type=job_type, idempotency_key=key, customer_profile=self.profile,
            connection=self.provider_connection if job_type == HealthJobType.FETCH_ROOK_DATA else None,
            scheduled_at=timezone.now() - timedelta(minutes=offset_minutes),
        )

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_regular_worker_excludes_fetch_rook_data_and_prioritizes_auth(self, processor):
        pulls = [self.add_job(HealthJobType.FETCH_ROOK_DATA, f"old-pull-{index}", 30) for index in range(4)]
        revoke = self.add_job(HealthJobType.REVOKE_ROOK_CONNECTION, "old-revoke", 20)
        refresh = self.add_job(HealthJobType.AUTHORISE_ROOK_CONNECTION, "new-refresh", 1)

        result = process_pending_rook_outbox(kind=QUEUE_KIND_AUTH, limit=10)
        processed_ids = [item["jobId"] for item in result]
        self.assertEqual(processed_ids[0], str(revoke.pk))
        self.assertEqual(processed_ids[1], str(refresh.pk))
        self.assertEqual(len(result), 2)
        self.assertEqual(len(set(processed_ids).intersection(str(job.pk) for job in pulls)), 0)
        self.assertEqual(RookOutbox.objects.filter(
            job_type=HealthJobType.FETCH_ROOK_DATA, status=HealthJobStatus.PENDING,
        ).count(), 4)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_dedicated_pull_worker_is_not_blocked_by_regular_backlog(self, processor):
        refresh = self.add_job(HealthJobType.AUTHORISE_ROOK_CONNECTION, "incoming-refresh", 1)
        pull = self.add_job(HealthJobType.FETCH_ROOK_DATA, "awaiting-pull", 30)
        for index in range(55):
            self.add_job(HealthJobType.AUTHORISE_ROOK_CONNECTION, f"auth-backlog-{index}", 40)

        results = process_pending_rook_outbox(kind=QUEUE_KIND_DATA_FETCH, limit=50)
        processed_ids = [item["jobId"] for item in results]
        self.assertEqual(len(results), 1)
        self.assertNotIn(str(refresh.pk), processed_ids)
        self.assertIn(str(pull.pk), processed_ids)
        self.assertEqual(processed_ids.count(str(pull.pk)), 1)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_full_auth_queue_never_yields_slot_to_slow_pull(self, processor):
        pull = self.add_job(HealthJobType.FETCH_ROOK_DATA, "waiting-pull", 30)
        for index in range(51):
            self.add_job(HealthJobType.AUTHORISE_ROOK_CONNECTION, f"refresh-{index}", 1)

        results = process_pending_rook_outbox(kind=QUEUE_KIND_AUTH, limit=50)
        processed_ids = [item["jobId"] for item in results]
        self.assertEqual(len(results), 50)
        self.assertNotIn(str(pull.pk), processed_ids)
        self.assertEqual(RookOutbox.objects.filter(
            job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
            status=HealthJobStatus.PENDING,
        ).count(), 1)

    @patch("wearables.services.job_processor.process_health_job", return_value={"test": True})
    def test_data_fetch_runs_when_only_fetch_jobs_exist(self, processor):
        self.add_job(HealthJobType.FETCH_ROOK_DATA, "fetch-only", 30)
        result = process_pending_rook_outbox(kind=QUEUE_KIND_DATA_FETCH, limit=50)
        self.assertEqual(len(result), 1)

    def test_manual_retry_reuses_open_job_and_creates_new_after_completion(self):
        first, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertTrue(created)
        second, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertFalse(created)
        self.assertEqual(first.pk, second.pk)
        third, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertFalse(created)
        self.assertEqual(third.pk, first.pk)
        self.assertEqual(RookOutbox.objects.filter(
            connection=self.provider_connection, job_type=HealthJobType.FETCH_ROOK_DATA,
        ).count(), 1)

        RookOutbox.objects.filter(pk=first.pk).update(status=HealthJobStatus.COMPLETED)
        later, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        self.assertTrue(created)
        self.assertNotEqual(later.pk, first.pk)

    def test_scheduler_respects_hourly_recovery_cooldown(self):
        first, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertTrue(created)
        RookOutbox.objects.filter(pk=first.pk).update(
            status=HealthJobStatus.COMPLETED, completed_at=timezone.now(),
        )
        another, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        self.assertIsNone(another)
        self.assertFalse(created)
        self.assertEqual(RookOutbox.objects.filter(
            connection=self.provider_connection, job_type=HealthJobType.FETCH_ROOK_DATA,
        ).count(), 1)

    def test_manual_retry_expedites_failed_recovery_without_creating_duplicates(self):
        first, _ = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile,
        )
        later = timezone.now() + timedelta(hours=1)
        RookOutbox.objects.filter(pk=first.pk).update(
            status=HealthJobStatus.FAILED, scheduled_at=later, attempt_count=1,
        )
        reused, created = enqueue_or_reuse_fetch_rook_data_job(
            connection=self.provider_connection, customer_profile=self.profile, manual=True,
        )
        reused.refresh_from_db()
        self.assertFalse(created)
        self.assertEqual(reused.pk, first.pk)
        self.assertLess(reused.scheduled_at, later)


class OAuthTransactionBoundaryTests(TransactionTestCase):
    @override_settings(ROOK_CLIENT_UUID="review-client", ROOK_CALLBACK_URL="https://r.test/r")
    @patch("wearables.services.connections.RookClient")
    def test_external_rook_authorization_check_runs_before_atomic_block(self, client_class):
        user = User.objects.create_user(email="pr143-oauth@example.com")
        UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=user)
        profile = CustomerProfile.objects.create(
            customer=customer, first_name="Callback", last_name="Test", is_main=True,
        )
        WearableConsent.objects.create(
            customer_profile=profile, status=ConsentStatus.GRANTED,
            granted_by=user, granted_at=timezone.now(), version="v1",
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
        self.assertFalse(RookOutbox.objects.filter(
            connection=connection, job_type=HealthJobType.AUTHORISE_ROOK_CONNECTION,
        ).exists())
        self.assertTrue(WearableConnectionEvent.objects.filter(
            connection=connection, event_type="oauth_state_verified",
        ).exists())
