"""Focused Phase 1 PRD contract regressions added after the gap audit.

Run with: uv run python manage.py test wearables.tests.test_prd_gap_closure
The database and ROOK HTTP calls are isolated; this does not replace a live
ROOK, iOS/Android or production-like performance acceptance run.
"""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from wearables.models import (
    HealthDomainSnapshot, HealthProcessingJob, RookHealthDocument,
    WearableConsent,
)
from wearables.serializers import DeviceConnectSerializer
from wearables.services.analytics import (
    card_state, confidence_level, dashboard_payload, history_window_availability,
    rolling_averages, trend_payload, invalidate_health_dashboard,
)
from wearables.services.connections import get_or_create_connection
from wearables.services.identity import get_or_create_rook_identity
from wearables.services.ingestion import ingest_rook_document, normalize_health_document
from wearables.services.job_processor import process_recovery_pull
from wearables.services.metrics import extract_metric_values, is_v1_display_metric
from wearables.services.timeline import timeline_payload
from wearables.utils.constants import (
    AuthorizationStatus, ConfidenceLevel, ConnectionStatus, ConsentStatus,
    HealthCardState, HealthDomain, HealthJobType, HistoricalImportStatus,
    PermissionStatus,
)


class PhaseOnePureContractTests(SimpleTestCase):
    def test_heart_metric_inside_sleep_summary_stays_heart(self):
        metrics = list(extract_metric_values(
            {"sleep_data": {"heart_rate": {"hr_resting": 58}},
             "sleep_duration_hours": 7.5}, data_structure="sleep_health_summary",
        ))
        self.assertEqual([m.domain for m in metrics if m.metric == "resting_heart_rate"], [HealthDomain.HEART])
        self.assertEqual([m.domain for m in metrics if m.metric == "sleep_duration_seconds"], [HealthDomain.SLEEP])

    def test_unrecognized_numeric_rook_value_not_exposed_in_v1(self):
        metrics = list(extract_metric_values(
            {"sleep_duration_hours": 7.5, "experimental_signal_float": 91.4},
            data_structure="sleep_health_summary",
        ))
        self.assertTrue(any(m.metric == "experimental_signal" for m in metrics))
        self.assertFalse(is_v1_display_metric(HealthDomain.SLEEP, "experimental_signal"))
        self.assertTrue(is_v1_display_metric(HealthDomain.SLEEP, "sleep_duration_seconds"))

    def test_sleep_session_start_end_and_stages_are_recognized(self):
        metrics = list(extract_metric_values({
            "sleep_start_datetime_string": "2026-10-15T23:00:00Z",
            "sleep_end_datetime_string": "2026-10-16T07:00:00Z",
            "deep_sleep_duration_minutes": 75,
            "rem_sleep_duration_minutes": 100,
        }, data_structure="sleep_health_summary"))
        mapped = {m.metric: m.value for m in metrics}
        self.assertEqual(mapped["sleep_start_time"], "2026-10-15T23:00:00Z")
        self.assertEqual(mapped["sleep_end_time"], "2026-10-16T07:00:00Z")
        self.assertEqual(mapped["deep_sleep_duration_seconds"], 4500)
        self.assertEqual(mapped["rem_sleep_duration_seconds"], 6000)

    def test_stale_historical_data_does_not_unlock_recent_windows_or_trend(self):
        today = date(2026, 10, 16)
        days = [SimpleNamespace(local_date=today-timedelta(days=100-i),
                                metric="steps", maximum=6000) for i in range(28)]
        available = history_window_availability(days, today=today)
        self.assertFalse(available["7d"]["available"])
        self.assertFalse(available["30d"]["available"])
        self.assertFalse(available["90d"]["available"])
        trend = trend_payload(summaries=days, metric="steps", preferred_units="metric",
                              confidence=ConfidenceLevel.HIGH, today=today)
        self.assertFalse(trend["baseline"]["available"])
        self.assertEqual(confidence_level({"observationDays": 28, "ratio": 1},
                                          days, today=today), ConfidenceLevel.LOW)

    def test_lifetime_rollup_does_not_fabricate_recent_averages(self):
        today = date(2026, 10, 16)
        days = [SimpleNamespace(local_date=today-timedelta(days=100-i),
                                metric="steps", maximum=6000,
                                last_observed_at=None, updated_at=timezone.now())
                for i in range(28)]
        windows = rolling_averages(days, metric="steps", preferred_units="metric", today=today)
        self.assertFalse(windows["7d"]["available"])
        self.assertFalse(windows["30d"]["available"])
        self.assertTrue(windows["lifetime"]["available"])
        self.assertEqual(windows["lifetime"]["value"], 6000)

    def test_known_incapable_provider_is_unsupported_not_waiting(self):
        connection = SimpleNamespace(
            data_source="Oura", status=ConnectionStatus.ACTIVE,
            authorization_status=AuthorizationStatus.AUTHORIZED,
            disconnected_at=None, permission_status=PermissionStatus.GRANTED,
            capabilities=[], last_error_code="", import_status=HistoricalImportStatus.COMPLETED,
            last_successful_sync=timezone.now(), connected_at=timezone.now(),
        )
        self.assertEqual(card_state(domain=HealthDomain.BODY, summaries=[],
                                    connections=[connection], coverage={"missingDays": 0}),
                         HealthCardState.UNSUPPORTED)
        self.assertEqual(card_state(domain=HealthDomain.SLEEP, summaries=[],
                                    connections=[connection], coverage={"missingDays": 0}),
                         HealthCardState.WAITING_FOR_DATA)

    @override_settings(ROOK_PREEXISTING_ENABLED=True, ROOK_PROVISIONED_SOURCES=None)
    def test_connect_refuses_unconfigured_provider_while_catalogue_disables_it(self):
        serializer = DeviceConnectSerializer(data={
            "data_source": "Garmin", "consent_accepted": True, "consent_version": "v1",
        })
        self.assertFalse(serializer.is_valid())
        self.assertIn("data_source", serializer.errors)

    @override_settings(ROOK_PREEXISTING_ENABLED=True, ROOK_PROVISIONED_SOURCES=["Garmin"])
    def test_explicitly_provisioned_source_still_works(self):
        serializer = DeviceConnectSerializer(data={
            "data_source": "Garmin", "consent_accepted": True, "historical_days": 29,
        })
        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertEqual(serializer.validated_data["historical_days"], 7)


class PhaseOnePersistenceContractTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="phase1-gap-closure@example.com")
        UserAccount.objects.create(user=self.user, account_type=UserType.CUSTOMER)
        customer = Customer.objects.create(user=self.user)
        self.profile = CustomerProfile.objects.create(
            customer=customer, first_name="Phase", last_name="One", is_main=True,
        )
        self.identity = get_or_create_rook_identity(self.profile, timezone_name="UTC")
        WearableConsent.objects.create(
            customer_profile=self.profile, granted_by=self.user,
            status=ConsentStatus.GRANTED, version="v1", granted_at=timezone.now(),
        )
        self.garmin = get_or_create_connection(
            customer_profile=self.profile, identity=self.identity,
            data_source="Garmin", historical_days_requested=1,
        )
        self.garmin.status = ConnectionStatus.IMPORTING
        self.garmin.import_status = HistoricalImportStatus.RUNNING
        self.garmin.authorization_status = AuthorizationStatus.AUTHORIZED
        self.garmin.permission_status = PermissionStatus.GRANTED
        self.garmin.import_started_at = timezone.now()
        self.garmin.save()

    def document(self, *, day="2026-10-15", structure="physical_health_summary"):
        return {
            "user_id": self.identity.rook_user_id,
            "datetime": f"{day}T10:00:00+00:00",
            "data_structure": structure,
            "document_version": 1,
            "source_of_data_string": "Garmin",
            "accumulated_steps_int": 6500 if structure.startswith("physical") else None,
            **({"sleep_duration_hours": 8} if structure.startswith("sleep") else {}),
        }

    def process_document(self, payload):
        with self.captureOnCommitCallbacks(execute=True):
            received = ingest_rook_document(payload, signature_valid=True)
        with self.captureOnCommitCallbacks(execute=True):
            normalized = normalize_health_document(received["documentId"])
        return received, normalized

    def test_two_rook_pillars_same_day_version_receive_distinct_analytics_jobs(self):
        self.process_document(self.document(structure="physical_health_summary"))
        self.process_document(self.document(structure="sleep_health_summary"))
        keys = list(HealthProcessingJob.objects.filter(
            job_type=HealthJobType.REFRESH_ANALYTICS,
        ).values_list("idempotency_key", flat=True))
        self.assertEqual(len(keys), 2)
        self.assertEqual(len(set(keys)), 2)

    @override_settings(ROOK_PREEXISTING_ENABLED=True)
    @patch("wearables.services.job_processor.RookClient.get_processed_summaries")
    def test_import_success_requires_normalized_v1_observations(self, get_summaries):
        get_summaries.side_effect = lambda **kw: ([{
            "source_of_data_string": "Garmin", "accumulated_steps_int": 8000,
        }] if kw["health_pillar"] == "physical" else [])
        with self.captureOnCommitCallbacks(execute=True):
            result = process_recovery_pull(SimpleNamespace(connection_id=self.garmin.pk))
        self.garmin.refresh_from_db()
        self.assertEqual(result["importedDocumentCount"], 1)
        self.assertFalse(result["partial"])
        self.assertEqual(self.garmin.import_status, HistoricalImportStatus.COMPLETED)
        self.assertTrue(RookHealthDocument.objects.filter(status="processed").exists())

    @override_settings(ROOK_PREEXISTING_ENABLED=True)
    @patch("wearables.services.job_processor.normalize_health_document", return_value={"skipped": True})
    @patch("wearables.services.job_processor.RookClient.get_processed_summaries")
    def test_failed_normalization_cannot_be_reported_as_completed(self, get_summaries, normalize):
        get_summaries.side_effect = lambda **kw: ([{
            "source_of_data_string": "Garmin", "accumulated_steps_int": 8000,
        }] if kw["health_pillar"] == "physical" else [])
        with self.captureOnCommitCallbacks(execute=True):
            result = process_recovery_pull(SimpleNamespace(connection_id=self.garmin.pk))
        self.garmin.refresh_from_db()
        self.assertTrue(result["partial"])
        self.assertEqual(result["failedDocumentCount"], 1)
        self.assertEqual(self.garmin.import_status, HistoricalImportStatus.FAILED)
        self.assertIsNone(self.garmin.import_completed_at)

    def test_timeline_gaps_are_not_dependent_on_page_size(self):
        self.process_document(self.document(day="2026-10-08"))
        self.process_document(self.document(day="2026-10-13"))
        for offset in (0, 1):
            result = timeline_payload(customer_profile=self.profile,
                                      start_date=None, end_date=None, domain="activity",
                                      offset=offset, limit=1)
            self.assertEqual(result["gapScope"], "filtered_timeline")
            self.assertEqual(len(result["gaps"]), 1)
            self.assertEqual(result["gaps"][0]["missingDays"], 4)

    def test_snapshot_cache_reuse_and_invalidation_across_reads(self):
        def sample_card(**kw):
            return {"id": kw["domain"], "state": "waiting_for_data",
                    "graph": {"confidence": "unknown"}}
        with patch("wearables.services.analytics.build_domain_card", side_effect=sample_card) as build:
            dashboard_payload(self.profile)
            self.assertEqual(build.call_count, 6)
            dashboard_payload(self.profile)
            self.assertEqual(build.call_count, 6)
            invalidate_health_dashboard(self.profile)
            self.assertEqual(HealthDomainSnapshot.objects.filter(customer_profile=self.profile).count(), 0)
            dashboard_payload(self.profile)
            self.assertEqual(build.call_count, 12)
