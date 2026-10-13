"""Database-free protections for the synthetic staging-only login shortcut."""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from rest_framework.test import APIRequestFactory

from accounts.verifications.utils.direct_login_testing import (
    TEST_LOGIN_EMAIL_BY_PHONE,
    direct_phone_login_testing_is_enabled,
)
from accounts.verifications.views import DirectPhoneLoginView


STAGING_KEY = "test-value-not-a-real-secret-0123456789abcdef"


class SyntheticDirectPhoneLoginTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()

    def post(self, *, key="", phone="+919999900101", remote_addr="127.0.0.1", host="testserver"):
        return DirectPhoneLoginView.as_view()(
            self.factory.post(
                "/auth/login-phone-direct/",
                {"phone": phone},
                format="json",
                HTTP_X_TEST_LOGIN_KEY=key,
                REMOTE_ADDR=remote_addr,
                HTTP_HOST=host,
            )
        )

    @override_settings(
        SETTINGS_MODULE="core.settings.production",
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
    )
    def test_production_rejects_direct_login_even_if_flag_is_set(self):
        self.assertFalse(direct_phone_login_testing_is_enabled())
        self.assertEqual(self.post(key=STAGING_KEY).status_code, 404)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        TEST_PHONE_LOGIN_ENABLED=False,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
    )
    def test_staging_is_disabled_by_default(self):
        self.assertEqual(self.post(key=STAGING_KEY).status_code, 404)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY="short",
    )
    def test_staging_rejects_weak_testing_key(self):
        self.assertEqual(self.post(key="short").status_code, 404)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
    )
    def test_staging_requires_correct_key(self):
        self.assertEqual(self.post().status_code, 403)
        self.assertEqual(self.post(key="wrong-key").status_code, 403)

    @override_settings(
        SETTINGS_MODULE="core.settings.staging",
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
    )
    @patch.object(DirectPhoneLoginView, "get_serializer")
    def test_staging_key_allows_seeded_serializer_to_issue_tokens(self, serializer_mock):
        serializer_mock.return_value.validated_data = {
            "access": "example-access",
            "refresh": "example-refresh",
        }
        result = self.post(key=STAGING_KEY)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data["data"]["access"], "example-access")
        serializer_mock.return_value.is_valid.assert_called_once_with(
            raise_exception=True
        )

    @override_settings(
        SETTINGS_MODULE="core.settings.development",
        DEBUG=True,
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
        ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
    )
    @patch.object(DirectPhoneLoginView, "get_serializer")
    def test_localhost_dev_allows_no_key(self, serializer_mock):
        serializer_mock.return_value.validated_data = {"access": "test-token"}
        response = self.post(host="localhost:8000")
        self.assertEqual(response.status_code, 200)

    @override_settings(
        SETTINGS_MODULE="core.settings.development",
        DEBUG=True,
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY=STAGING_KEY,
        ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
    )
    def test_non_loopback_dev_still_requires_key(self):
        self.assertEqual(
            self.post(host="localhost:8000", remote_addr="10.0.0.2").status_code,
            403,
        )
        self.assertEqual(self.post(host="example.org").status_code, 400)

    @override_settings(
        SETTINGS_MODULE="core.settings.development",
        DEBUG=True,
        TEST_PHONE_LOGIN_ENABLED=True,
        TEST_PHONE_LOGIN_KEY="",
        ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
    )
    @patch.object(DirectPhoneLoginView, "get_serializer")
    def test_local_dev_can_omit_key_entirely(self, serializer_mock):
        serializer_mock.return_value.validated_data = {"access": "test-token"}
        self.assertEqual(self.post(host="localhost:8000").status_code, 200)
        self.assertEqual(
            self.post(host="localhost:8000", remote_addr="10.1.1.1").status_code,
            403,
        )

    def test_only_eight_specific_phone_and_email_pairs_are_allowlisted(self):
        self.assertEqual(len(TEST_LOGIN_EMAIL_BY_PHONE), 8)
        self.assertEqual(
            TEST_LOGIN_EMAIL_BY_PHONE["+91-9999900101"],
            "biopeak-direct-test-01@example.com",
        )
        self.assertNotIn("+919888888888", TEST_LOGIN_EMAIL_BY_PHONE)
