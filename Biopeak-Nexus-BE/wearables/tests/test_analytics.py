from datetime import date, timedelta
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from django.utils import timezone

from wearables.services.analytics import (
    build_domain_card,
    connection_priority_state,
    current_value_payload,
    history_window_availability,
)
from wearables.utils.constants import (
    ConnectionStatus, HealthCardState, HealthDomain, PermissionStatus, PreferredUnits,
)


class AnalyticsAvailabilityTests(TestCase):
    def test_no_connections_is_not_reported_as_disconnected(self):
        self.assertIsNone(connection_priority_state([]))

    def test_history_windows_use_prd_observation_thresholds(self):
        today = timezone.now().date()
        summaries = [
            SimpleNamespace(local_date=today - timedelta(days=i), metric="steps", maximum=5000.0)
            for i in range(60)
        ]
        availability = history_window_availability(summaries, today=today)

        self.assertTrue(availability["7d"]["available"])
        self.assertTrue(availability["30d"]["available"])
        self.assertTrue(availability["90d"]["available"])
        self.assertEqual(availability["30d"]["requiredObservationDays"], 21)
        self.assertEqual(availability["90d"]["requiredObservationDays"], 60)

    def test_history_window_rejects_old_data(self):
        today = timezone.now().date()
        old = [
            SimpleNamespace(local_date=today - timedelta(days=i + 120), metric="steps", maximum=5000.0)
            for i in range(70)
        ]
        availability = history_window_availability(old, today=today)
        self.assertFalse(availability["7d"]["available"])
        self.assertFalse(availability["30d"]["available"])
        self.assertFalse(availability["90d"]["available"])

    def test_secondary_denied_provider_does_not_hide_healthy_data(self):
        good = SimpleNamespace(
            status=ConnectionStatus.ACTIVE,
            permission_status=PermissionStatus.GRANTED,
            capabilities=["heart"],
            import_status="completed",
            last_successful_sync=timezone.now(),
        )
        denied = SimpleNamespace(
            status=ConnectionStatus.ACTIVE,
            permission_status=PermissionStatus.DENIED,
            capabilities=["heart"],
            import_status="completed",
            last_successful_sync=timezone.now(),
        )
        state = connection_priority_state(
            [good, denied], domain=HealthDomain.HEART, has_data=True
        )
        self.assertNotEqual(state, HealthCardState.PERMISSION_REQUIRED)

    def test_requested_seven_day_card_graph_filters_ninety_day_history(self):
        today = timezone.now().date()
        summaries = [
            SimpleNamespace(
                local_date=today - timedelta(days=i), metric="steps", maximum=2000.0 + i,
                last_observed_at=timezone.now() - timedelta(days=i),
            )
            for i in reversed(range(90))
        ]
        profile = SimpleNamespace(pk="card-window-test", rook_identity=None)
        with patch("wearables.services.analytics.headline_series", return_value=("steps", summaries)), \
             patch("wearables.services.analytics.HealthObservation.objects.filter") as observations:
            observations.return_value.exists.return_value = False
            observations.return_value.values_list.return_value.iterator.return_value = iter(())
            card = build_domain_card(
                customer_profile=profile, domain=HealthDomain.ACTIVITY,
                connections=[], preferred_units=PreferredUnits.METRIC, days=7,
            )
        self.assertEqual(card["graph"]["requestedWindowDays"], 7)
        self.assertEqual(len(card["graph"]["points"]), 7)
        self.assertTrue(all(point["date"] >= today - timedelta(days=6) for point in card["graph"]["points"]))
        self.assertEqual(card["graph"]["windowAvailability"]["90d"]["observationDays"], 90)

    def test_missing_workout_values_are_not_converted_to_zero(self):
        summary = SimpleNamespace(
            metric="workout_count",
            total=None,
            local_date=date(2026, 10, 8),
            last_observed_at=None,
        )

        current_value = current_value_payload(
            summaries=[summary],
            metric="workout_count",
            preferred_units=PreferredUnits.METRIC,
            domain=HealthDomain.WORKOUTS,
        )

        self.assertEqual(current_value, {"available": False})
