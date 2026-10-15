"""PRD Phase 1 acceptance regressions: idempotency, history, trend and cache."""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from unittest.mock import patch

from django.core.cache import caches
from django.test import SimpleTestCase, TestCase, override_settings

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import HealthDailySummary, HealthObservation, RookHealthDocument, WearableConsent
from wearables.services.analytics import (
    dashboard_payload, health_cache_key, invalidate_health_dashboard,
    member_today, trend_direction, trend_payload,
)
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import (
    ingest_rook_document, normalize_health_document, remap_member_local_days,
)
from wearables.utils.constants import ConfidenceLevel, ConsentStatus, TrendDirection


class PhaseOnePersistenceRegressionTests(TestCase):
    def setUp(self):
        user = User.objects.create_user(email="phase1-history-regression@example.com")
        UserAccount.objects.create(user=user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="History", last_name="Test", is_main=True,
        )
        self.identity = get_or_create_rook_identity(self.profile, timezone_name="UTC")

    def payload(self, version, steps, moment="2026-10-08T10:00:00+00:00", event_id="abc"):
        return {
            "user_id": self.identity.rook_user_id,
            "client_uuid": "phase1-test",
            "datetime": moment,
            "data_structure": "physical_health_summary",
            "document_version": version,
            "document_id": event_id,
            "source_of_data_string": "Garmin",
            "accumulated_steps_int": steps,
        }

    def ingest_and_process(self, payload):
        with self.captureOnCommitCallbacks(execute=True):
            result = ingest_rook_document(payload, signature_valid=True)
        if result.get("queued"):
            with self.captureOnCommitCallbacks(execute=True):
                normalize_health_document(result["documentId"])
        return result

    def test_higher_document_version_keeps_previous_observation_but_excludes_from_rollups(self):
        self.ingest_and_process(self.payload(1, 5000, event_id="old"))
        self.ingest_and_process(self.payload(2, 7000, event_id="new"))
        self.assertEqual(RookHealthDocument.objects.count(), 1)
        self.assertEqual(HealthObservation.objects.filter(metric="steps").count(), 2)
        self.assertEqual(HealthObservation.objects.filter(metric="steps", is_current=True).count(), 1)
        self.assertEqual(HealthObservation.objects.get(metric="steps", is_current=True).numeric_value, 7000)
        self.assertEqual(HealthDailySummary.objects.get(metric="steps").maximum, 7000)

    def test_replaying_normalization_keeps_exactly_one_active_version(self):
        result = self.ingest_and_process(self.payload(1, 5000))
        self.ingest_and_process(self.payload(2, 7000))
        with self.captureOnCommitCallbacks(execute=True):
            normalize_health_document(result["documentId"])
        self.assertEqual(HealthObservation.objects.filter(metric="steps", is_current=True).count(), 1)

    def test_granular_readings_roll_up_on_both_calendar_days(self):
        payload = self.payload(1, 4000)
        payload["hr_events"] = [
            {"datetime_string": "2026-10-08T23:30:00Z", "hr_avg_float": 66},
            {"datetime_string": "2026-10-09T01:30:00Z", "hr_avg_float": 70},
        ]
        self.ingest_and_process(payload)
        measurements = list(
            HealthObservation.objects.filter(metric="average_heart_rate").order_by("observed_at")
        )
        self.assertEqual([item.local_date for item in measurements], [date(2026, 10, 8), date(2026, 10, 9)])
        self.assertEqual(
            HealthDailySummary.objects.filter(metric="average_heart_rate").count(), 2
        )

    def test_correction_moves_reading_without_leaving_stale_summary(self):
        old = self.payload(1, 4000)
        old["hr_events"] = [{"datetime_string": "2026-10-08T23:30:00Z", "hr_avg_float": 66}]
        self.ingest_and_process(old)
        new = self.payload(2, 4000)
        new["hr_events"] = [{"datetime_string": "2026-10-09T01:30:00Z", "hr_avg_float": 70}]
        self.ingest_and_process(new)
        self.assertFalse(HealthDailySummary.objects.filter(
            metric="average_heart_rate", local_date=date(2026, 10, 8)
        ).exists())
        self.assertEqual(HealthDailySummary.objects.get(
            metric="average_heart_rate", local_date=date(2026, 10, 9)
        ).latest, 70)

    def test_explicit_consent_withdrawal_blocks_future_documents(self):
        now = datetime.now(dt_timezone.utc)
        WearableConsent.objects.create(
            customer_profile=self.profile, status=ConsentStatus.REVOKED,
            version="test-v1", granted_at=now, revoked_at=now,
        )
        result = ingest_rook_document(self.payload(1, 4000), signature_valid=True)
        self.assertEqual(result["reason"], "consent_revoked")
        self.assertFalse(RookHealthDocument.objects.exists())

    def test_timezone_remap_rebuilds_calendar_buckets_without_losing_data(self):
        self.ingest_and_process(self.payload(1, 3500, moment="2026-10-08T23:30:00Z"))
        observation = HealthObservation.objects.get(metric="steps")
        self.assertEqual(observation.local_date, date(2026, 10, 8))
        self.identity.timezone_name = "Asia/Kolkata"
        self.identity.save(update_fields=["timezone_name", "updated_at"])
        with self.captureOnCommitCallbacks(execute=True):
            result = remap_member_local_days(self.profile)
        observation.refresh_from_db()
        self.assertEqual(result["remapped"], 1)
        self.assertEqual(observation.local_date, date(2026, 10, 9))
        self.assertEqual(HealthObservation.objects.count(), 1)
        self.assertTrue(HealthDailySummary.objects.filter(local_date=date(2026, 10, 9)).exists())


class PhaseOneAnalyticsRegressionTests(SimpleTestCase):
    def test_provisional_steps_mmc_is_relative_to_baseline(self):
        self.assertEqual(trend_direction(
            metric="steps", current_mean=1090, baseline_mean=1000,
            confidence=ConfidenceLevel.HIGH,
        ), TrendDirection.STABLE)
        self.assertEqual(trend_direction(
            metric="steps", current_mean=1150, baseline_mean=1000,
            confidence=ConfidenceLevel.HIGH,
        ), TrendDirection.IMPROVING)

    def test_weight_requires_program_goal_for_improvement_label(self):
        result = trend_direction(
            metric="weight_kg", current_mean=75, baseline_mean=78,
            confidence=ConfidenceLevel.HIGH,
        )
        self.assertEqual(result, TrendDirection.UNKNOWN)

    def test_seven_days_does_not_fake_prior_28_day_baseline(self):
        summaries = [
            SimpleNamespace(metric="steps", maximum=6000, local_date=date(2026, 10, 1) + timedelta(days=i))
            for i in range(7)
        ]
        result = trend_payload(
            summaries=summaries, metric="steps",
            confidence=ConfidenceLevel.HIGH, preferred_units="metric",
        )
        self.assertFalse(result["baseline"]["available"])
        self.assertTrue(result["interpretationSuppressed"])

    @override_settings(CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "health": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "phase-one-cache-test"},
    })
    def test_dashboard_cache_and_invalidation(self):
        profile = SimpleNamespace(pk="phase-one-cache-profile")
        caches["health"].clear()
        with patch("wearables.services.analytics.health_cache_revision", return_value="static"), \
             patch("wearables.services.analytics.build_dashboard_cards", return_value=[]) as refresh:
            dashboard_payload(profile)
            dashboard_payload(profile)
            self.assertEqual(refresh.call_count, 1)
            invalidate_health_dashboard(profile)
            dashboard_payload(profile)
            self.assertEqual(refresh.call_count, 2)

    def test_member_timezone_date_uses_utc_instant_not_server_timezone(self):
        profile = SimpleNamespace(rook_identity=SimpleNamespace(timezone_name="Asia/Kolkata"))
        utc_time = datetime(2026, 10, 8, 23, 40, tzinfo=dt_timezone.utc)
        with patch("wearables.services.analytics.timezone.now", return_value=utc_time):
            self.assertEqual(member_today(profile), date(2026, 10, 9))
