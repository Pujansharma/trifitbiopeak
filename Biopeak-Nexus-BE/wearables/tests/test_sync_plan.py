"""Dependency-free tests: python -m unittest wearables.tests.test_sync_plan."""
from datetime import datetime, timedelta, timezone
import unittest

from wearables.services.sync_plan import (
    HEALTH_PILLARS, advance_sync_plan, create_sync_plan,
    remaining_sync_units, sync_plan_complete,
)


class SyncPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.now = datetime(2026, 11, 5, 18, 30, tzinfo=timezone.utc)

    def plan(self, *, flow="initial", cursor=None, days=7, timezone_name="Asia/Kolkata") -> dict:
        return create_sync_plan(requested_at=self.now, timezone_name=timezone_name,
                                previous_cursor=cursor, flow=flow, initial_days=days)

    def test_initial_import_is_seven_local_dates_and_three_pillars(self) -> None:
        plan = self.plan()
        units = list(remaining_sync_units(plan))
        self.assertEqual(plan["startDate"], "2026-10-31")
        self.assertEqual(plan["endDate"], "2026-11-06")
        self.assertEqual(len(units), 21)
        self.assertEqual(units[:3], [("2026-10-31", pillar) for pillar in HEALTH_PILLARS])

    def test_initial_ignores_old_cursor(self) -> None:
        self.assertEqual(self.plan(cursor=self.now - timedelta(days=50)), self.plan())

    def test_manual_rechecks_only_last_covered_day_forward(self) -> None:
        plan = self.plan(flow="manual", cursor=self.now - timedelta(days=2))
        self.assertEqual(plan["startDate"], "2026-11-04")
        self.assertEqual(len(list(remaining_sync_units(plan))), 9)

    def test_manual_does_not_silently_drop_a_gap_longer_than_seven_days(self) -> None:
        plan = self.plan(flow="manual", cursor=self.now - timedelta(days=20))
        self.assertEqual(len(list(remaining_sync_units(plan))), 63)

    def test_rolling_mode_always_rechecks_seven_days(self) -> None:
        self.assertEqual(len(list(remaining_sync_units(self.plan(flow="rolling", days=1)))), 21)

    def test_checkpoint_after_physical_resumes_sleep_not_physical(self) -> None:
        plan = self.plan()
        first = next(remaining_sync_units(plan))
        changed = advance_sync_plan(plan, summary_date=first[0], pillar=first[1], document_count=2)
        self.assertEqual(next(remaining_sync_units(changed)), ("2026-10-31", "sleep"))
        self.assertEqual(changed["documentCount"], 2)
        self.assertEqual(changed["requestCount"], 1)
        self.assertEqual(plan["requestCount"], 0)

    def test_checkpoint_after_body_advances_date(self) -> None:
        plan = self.plan()
        for day, pillar in list(remaining_sync_units(plan))[:3]:
            plan = advance_sync_plan(plan, summary_date=day, pillar=pillar, document_count=0)
        self.assertEqual(next(remaining_sync_units(plan)), ("2026-11-01", "physical"))

    def test_completed_plan_does_not_repeat_downloads(self) -> None:
        plan = self.plan()
        for day, pillar in list(remaining_sync_units(plan)):
            plan = advance_sync_plan(plan, summary_date=day, pillar=pillar, document_count=1)
        self.assertTrue(sync_plan_complete(plan))
        self.assertEqual(list(remaining_sync_units(plan)), [])
        self.assertEqual(plan["documentCount"], 21)

    def test_partial_plan_is_not_complete(self) -> None:
        self.assertFalse(sync_plan_complete(self.plan()))

    def test_window_end_is_frozen_at_request_time(self) -> None:
        self.assertEqual(self.plan()["windowEnd"], self.now.isoformat())

    def test_timezone_can_put_two_members_on_different_calendar_days(self) -> None:
        self.assertEqual(self.plan(timezone_name="UTC")["endDate"], "2026-11-05")
        self.assertEqual(self.plan()["endDate"], "2026-11-06")

    def test_future_cursor_is_clamped_to_current_local_date(self) -> None:
        self.assertEqual(len(list(remaining_sync_units(self.plan(flow="manual", cursor=self.now + timedelta(days=10))))), 3)

    def test_requested_history_is_bounded(self) -> None:
        self.assertEqual(len(list(remaining_sync_units(self.plan(days=29)))), 21)
        self.assertEqual(len(list(remaining_sync_units(self.plan(days=1)))), 3)

    def test_invalid_checkpoint_is_rejected(self) -> None:
        plan = {**self.plan(), "nextPillar": 9}
        with self.assertRaises(ValueError):
            list(remaining_sync_units(plan))

    def test_naive_request_timestamp_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            create_sync_plan(requested_at=datetime(2026, 11, 5), timezone_name="UTC",
                             previous_cursor=None, flow="initial")

    def test_checkpoint_resume_equivalence_for_every_unit(self) -> None:
        for checkpoint in range(22):
            with self.subTest(checkpoint=checkpoint):
                plan = self.plan()
                all_units = list(remaining_sync_units(plan))
                for day, pillar in all_units[:checkpoint]:
                    plan = advance_sync_plan(plan, summary_date=day, pillar=pillar, document_count=0)
                self.assertEqual(list(remaining_sync_units(plan)), all_units[checkpoint:])
