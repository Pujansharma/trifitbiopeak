"""Regression tests for profile-limited health job selection."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from django.test import SimpleTestCase

from wearables.services.job_processor import process_pending_health_jobs


class HealthJobFilterTests(SimpleTestCase):
    @patch("wearables.services.job_processor.HealthProcessingJob.objects")
    @patch("wearables.services.job_processor.reset_stale_health_jobs")
    def test_limits_jobs_by_customer_before_selecting(self, reset_stale, objects):
        profile_id = uuid4()
        queryset = MagicMock()
        objects.filter.return_value = queryset
        queryset.filter.return_value = queryset
        queryset.order_by.return_value = queryset
        queryset.values_list.return_value.__getitem__.return_value = []

        self.assertEqual(
            process_pending_health_jobs(limit=1, customer_profile_id=profile_id), []
        )
        reset_stale.assert_called_once_with(customer_profile_id=profile_id)
        queryset.filter.assert_called_once_with(customer_profile_id=profile_id)
        queryset.values_list.return_value.__getitem__.assert_called_once_with(
            slice(None, 1, None)
        )

    def test_rejects_non_positive_limit(self):
        with self.assertRaisesRegex(ValueError, "limit must be at least 1"):
            process_pending_health_jobs(limit=0)
