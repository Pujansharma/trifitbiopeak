from datetime import datetime
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings

from accounts.centers.models import Center
from appointments.utils.calendar import format_center_datetime

UTC = ZoneInfo("UTC")


@override_settings(TIME_ZONE="Asia/Kolkata")
class FormatCenterDatetimeTests(SimpleTestCase):
    def setUp(self):
        self.center = Center(name="Format Center")

    def test_morning_time_in_center_timezone(self):
        moment = datetime(2026, 9, 5, 3, 30, tzinfo=UTC)
        self.assertEqual(
            format_center_datetime(self.center, moment), "05 Sep 2026, 09:00 AM"
        )

    def test_afternoon_uses_pm(self):
        moment = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
        self.assertEqual(
            format_center_datetime(self.center, moment), "15 Sep 2026, 02:30 PM"
        )

    def test_midnight_rolls_to_center_local_day(self):
        moment = datetime(2026, 9, 15, 18, 30, tzinfo=UTC)
        self.assertEqual(
            format_center_datetime(self.center, moment), "16 Sep 2026, 12:00 AM"
        )

    def test_naive_datetime_is_rejected(self):
        with self.assertRaises(ValueError):
            format_center_datetime(self.center, datetime(2026, 9, 15, 9, 0))
