"""Focused tests for the additive Phase 1 client-safe functionality.

Run on Python >=3.14 after client approval for inherited startup issues:
    uv run python manage.py test wearables.tests.test_client_safe_integration
"""
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase, override_settings

from wearables.services.oauth import (
    OAuthStateError,
    _decode_state,
    callback_url_for_connection,
)
from wearables.services.timeline import _page_gaps, timeline_payload
from wearables.services.client import RookConfigurationError
from wearables.utils.constants import HealthCardState


class CallbackStateContractTests(SimpleTestCase):
    @override_settings(ROOK_CALLBACK_URL="https://api.example.org/r")
    @patch("wearables.services.oauth.WearableConnectionEvent.objects.create")
    def test_callback_state_opaque_and_separate_from_customer_identity(self, create):
        create.return_value = SimpleNamespace()
        connection = SimpleNamespace(status="authorizing", data_source="Garmin")
        result = callback_url_for_connection(connection, actor_user=object())
        url = urlsplit(result)
        token = url.path.rsplit("/", 1)[-1]
        self.assertEqual(url.hostname, "api.example.org")
        self.assertLessEqual(len(result), 50)
        self.assertEqual(_decode_state(token), create.call_args.kwargs["payload"]["nonceDigest"])
        self.assertNotIn("customer_profile", token)
        self.assertNotIn("rook_user_id", token)
        self.assertEqual(create.call_args.kwargs["event_type"], "oauth_state_pending")
        self.assertNotIn(token, str(create.call_args.kwargs["payload"]))

    def test_bad_state_rejected(self):
        for invalid in ("", "one", "hello.world", "?" * 16, "x" * 17):
            with self.subTest(invalid=invalid), self.assertRaises(OAuthStateError):
                _decode_state(invalid)

    @override_settings(ROOK_CALLBACK_URL="http://insecure.example/r")
    def test_non_https_callback_rejected(self):
        with self.assertRaises(RookConfigurationError):
            callback_url_for_connection(SimpleNamespace(), actor_user=object())

    @override_settings(ROOK_CALLBACK_URL="https://a-very-long-backend-domain.example.com/r")
    def test_long_callback_rejected_before_db_write(self):
        with patch("wearables.services.oauth.WearableConnectionEvent.objects.create") as create:
            with self.assertRaises(RookConfigurationError):
                callback_url_for_connection(SimpleNamespace(), actor_user=object())
            create.assert_not_called()

    @override_settings(ROOK_CLIENT_UUID="tenant-rook-client")
    def test_client_uuid_mismatch_rejected_before_db_query(self):
        from wearables.services.oauth import complete_oauth_callback
        with self.assertRaises(OAuthStateError):
            complete_oauth_callback("aaaabbbbccccdddd", rook_client_uuid="other-client", rook_user_id="x")


class CombinedTimelineContractTests(SimpleTestCase):
    def test_gaps_ignore_clinical_entries(self):
        entries = [
            {"sourceType": "wearable", "domain": "sleep", "localDate": date(2026, 10, 1)},
            {"sourceType": "wearable", "domain": "sleep", "localDate": date(2026, 10, 4)},
            {"sourceType": "lab", "domain": None, "localDate": date(2026, 10, 2)},
        ]
        gaps = _page_gaps(entries)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["missingDays"], 2)
        self.assertEqual(gaps[0]["state"], HealthCardState.HISTORICAL_GAP)

    @override_settings(TIMELINE_INCLUDE_LEGACY_RESULTS=True)
    @patch("wearables.services.timeline._clinical_entries")
    @patch("wearables.services.timeline._wearable_entries")
    def test_timeline_merges_sorted_profile_scoped_sources_and_paginates(self, wearable, clinical):
        when = lambda n: datetime(2026, 10, n, tzinfo=timezone.utc)
        wearable.return_value = [
            {"id": "w", "timestamp": when(2), "sourceType": "wearable", "domain": "sleep", "localDate": date(2026, 10, 2)},
        ]
        clinical.return_value = [
            {"id": "lab", "timestamp": when(3), "sourceType": "lab", "domain": None},
            {"id": "assess", "timestamp": when(1), "sourceType": "assessment", "domain": None},
        ]
        profile = SimpleNamespace(rook_identity=SimpleNamespace(timezone_name="UTC"))
        payload = timeline_payload(customer_profile=profile, start_date=None, end_date=None,
                                   domain=None, offset=0, limit=2)
        self.assertEqual([e["id"] for e in payload["entries"]], ["lab", "w"])
        self.assertEqual(payload["nextOffset"], 2)
        wearable.assert_called_once()
        clinical.assert_called_once()

    @override_settings(TIMELINE_INCLUDE_LEGACY_RESULTS=True)
    @patch("wearables.services.timeline._clinical_entries")
    @patch("wearables.services.timeline._wearable_entries", return_value=[])
    def test_domain_filtered_timeline_never_reads_clinical_data(self, wearable, clinical):
        timeline_payload(customer_profile=SimpleNamespace(), start_date=None,
                         end_date=None, domain="heart", offset=0, limit=10)
        clinical.assert_not_called()
