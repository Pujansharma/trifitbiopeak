"""Pure policy/coverage tests: runnable without Django, AWS or credentials."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import unittest
from zoneinfo import ZoneInfo

from wearables.services.rate_policy import budget_decision, retry_after_time, seconds_until
from wearables.services.sync_policy import manual_sync_allowed, next_manual_sync_at, ManualSyncCooldown
from wearables.services.sync_plan import create_sync_plan, remaining_sync_units, advance_sync_plan, sync_plan_complete

NOW = datetime(2026, 11, 6, 4, 30, tzinfo=timezone.utc)


class ManualSyncPolicyTests(unittest.TestCase):
    def test_first_request_allowed(self):
        self.assertTrue(manual_sync_allowed(now=NOW, last_accepted_at=None))

    def test_next_allowed_is_six_elapsed_hours(self):
        self.assertEqual(next_manual_sync_at(NOW), NOW + timedelta(hours=6))

    def test_before_boundary_denied(self):
        self.assertFalse(manual_sync_allowed(now=NOW + timedelta(hours=6, microseconds=-1), last_accepted_at=NOW))

    def test_exact_boundary_allowed(self):
        self.assertTrue(manual_sync_allowed(now=NOW + timedelta(hours=6), last_accepted_at=NOW))

    def test_after_boundary_allowed(self):
        self.assertTrue(manual_sync_allowed(now=NOW + timedelta(hours=7), last_accepted_at=NOW))

    def test_equivalent_local_and_utc_instants(self):
        self.assertEqual(next_manual_sync_at(NOW.astimezone(ZoneInfo('Asia/Kolkata'))), NOW + timedelta(hours=6))

    def test_no_previous_next_time(self):
        self.assertIsNone(next_manual_sync_at(None))

    def test_naive_request_rejected(self):
        with self.assertRaises(ValueError):
            manual_sync_allowed(now=NOW.replace(tzinfo=None), last_accepted_at=None)

    def test_naive_previous_rejected(self):
        with self.assertRaises(ValueError):
            next_manual_sync_at(NOW.replace(tzinfo=None))

    def test_clock_behind_previous_not_allowed(self):
        self.assertFalse(manual_sync_allowed(now=NOW, last_accepted_at=NOW + timedelta(seconds=1)))

    def test_elapsed_cooldown_across_dst_fall_back(self):
        start = datetime(2026, 11, 1, 0, 30, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(next_manual_sync_at(start), start.astimezone(timezone.utc) + timedelta(hours=6))

    def test_elapsed_cooldown_across_dst_spring_forward(self):
        start = datetime(2026, 3, 8, 0, 30, tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(next_manual_sync_at(start), start.astimezone(timezone.utc) + timedelta(hours=6))

    def test_exception_carries_existing_job_without_new_admission(self):
        error = ManualSyncCooldown(NOW + timedelta(hours=6), 'job-one')
        self.assertEqual(error.job_id, 'job-one')
        self.assertEqual(error.next_allowed_at, NOW + timedelta(hours=6))


class RatePolicyTests(unittest.TestCase):
    def decision(self, **overrides):
        values = dict(now=NOW, budget_date=NOW.date(), requests_today=0,
                      next_request_at=None, blocked_until=None,
                      requests_per_minute=60, requests_per_day=1000)
        values.update(overrides)
        return budget_decision(**values)

    def test_reservation_spends_one_request(self):
        result = self.decision()
        self.assertTrue(result['allowed'])
        self.assertEqual(result['requests_today'], 1)

    def test_per_minute_spacing(self):
        self.assertEqual(self.decision()['next_request_at'], NOW + timedelta(seconds=1))

    def test_different_rate_spacing(self):
        self.assertEqual(self.decision(requests_per_minute=12)['next_request_at'], NOW + timedelta(seconds=5))

    def test_wait_before_next_request(self):
        result = self.decision(next_request_at=NOW + timedelta(seconds=2))
        self.assertFalse(result['allowed'])
        self.assertEqual(result['retry_at'], NOW + timedelta(seconds=2))

    def test_exact_rate_boundary_allowed(self):
        self.assertTrue(self.decision(next_request_at=NOW)['allowed'])

    def test_provider_backoff_beats_spacing(self):
        result = self.decision(next_request_at=NOW + timedelta(seconds=1), blocked_until=NOW + timedelta(minutes=2))
        self.assertEqual(result['retry_at'], NOW + timedelta(minutes=2))

    def test_expired_provider_backoff_allows(self):
        self.assertTrue(self.decision(blocked_until=NOW - timedelta(seconds=1))['allowed'])

    def test_daily_budget_defers_until_utc_midnight(self):
        result = self.decision(requests_today=1000)
        self.assertFalse(result['allowed'])
        self.assertEqual(result['retry_at'], datetime(2026, 11, 7, tzinfo=timezone.utc))

    def test_new_utc_day_resets_counter(self):
        result = self.decision(budget_date=(NOW - timedelta(days=1)).date(), requests_today=1000)
        self.assertEqual(result['requests_today'], 1)

    def test_daily_budget_not_reset_by_member_midnight(self):
        local = datetime(2026, 11, 7, 1, tzinfo=ZoneInfo('Asia/Kolkata'))
        result = self.decision(now=local, budget_date=NOW.date(), requests_today=1000)
        self.assertFalse(result['allowed'])

    def test_provider_backoff_can_survive_daily_reset(self):
        until = NOW + timedelta(days=2)
        self.assertEqual(self.decision(requests_today=1000, blocked_until=until)['retry_at'], until)

    def test_invalid_budgets_rejected(self):
        for overrides in ({'requests_per_minute': 0}, {'requests_per_day': -1}, {'now': NOW.replace(tzinfo=None)}):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.decision(**overrides)

    def test_retry_after_numeric(self):
        self.assertEqual(retry_after_time('120', now=NOW), NOW + timedelta(seconds=120))

    def test_retry_after_date(self):
        self.assertEqual(retry_after_time(format_datetime(NOW + timedelta(minutes=3)), now=NOW), NOW + timedelta(minutes=3))

    def test_retry_after_past_date(self):
        self.assertEqual(retry_after_time(format_datetime(NOW - timedelta(minutes=3)), now=NOW), NOW + timedelta(seconds=1))

    def test_retry_after_invalid_falls_back(self):
        for value in (None, '', 'not-a-date', '-5'):
            self.assertEqual(retry_after_time(value, now=NOW), NOW + timedelta(seconds=60))

    def test_retry_after_extreme_numeric_is_finite(self):
        self.assertEqual(retry_after_time('999999999999', now=NOW), NOW + timedelta(days=7))

    def test_wait_rounds_up(self):
        self.assertEqual(seconds_until(NOW + timedelta(seconds=1.1), NOW), 2)

    def test_wait_never_zero(self):
        self.assertEqual(seconds_until(NOW, NOW), 1)


class CoverageSafetyTests(unittest.TestCase):
    def plan(self, **overrides):
        values = dict(requested_at=NOW, timezone_name='Asia/Kolkata', previous_cursor=None, flow='initial')
        values.update(overrides)
        return create_sync_plan(**values)

    def test_rejects_naive_saved_cursor(self):
        with self.assertRaises(ValueError):
            self.plan(previous_cursor=NOW.replace(tzinfo=None))

    def test_cannot_skip_pillar(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            advance_sync_plan(plan, summary_date=plan['nextDate'], pillar='body', document_count=1)

    def test_cannot_skip_date(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            advance_sync_plan(plan, summary_date=plan['endDate'], pillar='physical', document_count=1)

    def test_cannot_accept_negative_document_count(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            advance_sync_plan(plan, summary_date=plan['nextDate'], pillar='physical', document_count=-1)

    def test_complete_only_after_all_units(self):
        plan = self.plan()
        for index, (day, pillar) in enumerate(list(remaining_sync_units(plan)), start=1):
            plan = advance_sync_plan(plan, summary_date=day, pillar=pillar, document_count=1)
            self.assertEqual(sync_plan_complete(plan), index == 21)
        self.assertEqual(plan['documentCount'], 21)

    def test_newer_target_preserves_overlap(self):
        followup = self.plan(requested_at=NOW + timedelta(days=2), previous_cursor=NOW, flow='followup')
        self.assertEqual(len(list(remaining_sync_units(followup))), 9)
        self.assertEqual(followup['startDate'], NOW.astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat())


if __name__ == '__main__':
    unittest.main()
