"""Focused tests for the additive Phase 1 client-safe functionality.

Run on Python >=3.14 after client approval for inherited startup issues:
    uv run python manage.py test wearables.tests.test_client_safe_integration
"""
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

from django.test import SimpleTestCase, override_settings

from wearables.services.oauth import (
    OAuthStateError,
    _decode_state,
    callback_url_for_connection,
    complete_oauth_callback,
)
from wearables.services.client import RookConfigurationError


class CallbackStateContractTests(SimpleTestCase):
    @override_settings(ROOK_CALLBACK_URL="https://api.example.org/r")
    @patch("wearables.services.oauth.WearableConnectionEvent.objects.create")
    def test_callback_state_opaque_and_separate_from_customer_identity(self, create):
        create.return_value = SimpleNamespace()
        connection = SimpleNamespace(status="authorizing", data_source="Garmin", authorization_generation="test-generation")
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
        with self.assertRaises(OAuthStateError):
            complete_oauth_callback("aaaabbbbccccdddd", rook_client_uuid="other-client", rook_user_id="x")

