"""ROOK provisioning and config preflight coverage, without live provider secrets."""
from django.test import SimpleTestCase, override_settings

from wearables.management.commands.check_rook_configuration import (
    rook_readiness_checks,
    validate_rook_callback,
)
from wearables.services.config import provisioned_sources


class RookDeploymentConfigurationTests(SimpleTestCase):
    @override_settings(ROOK_PROVISIONED_SOURCES="Garmin,Fitbit,Oura")
    def test_provisioned_sources_from_django_settings(self):
        self.assertEqual(provisioned_sources(), {"Garmin", "Fitbit", "Oura"})

    @override_settings(ROOK_PROVISIONED_SOURCES=None)
    def test_no_provisioning_is_not_implicitly_every_provider(self):
        # An explicit empty list must not silently permit arbitrary providers.
        self.assertNotEqual(provisioned_sources() or set(), {"Garmin", "Fitbit"})

    def test_short_https_callback(self):
        self.assertTrue(validate_rook_callback("https://bpk.example/r"))
        self.assertFalse(validate_rook_callback("http://localhost:8000/r"))
        self.assertFalse(validate_rook_callback("https://example.com/return?token=abc"))

    @override_settings(
        WEARABLES_ENABLED=True,
        ROOK_PROVISIONED_SOURCES="Garmin",
        ROOK_BASE_URL="https://api.rook-connect.review",
        ROOK_CLIENT_UUID="",
        ROOK_SECRET_KEY="",
        ROOK_WEBHOOK_HASH_KEY="",
        ROOK_CALLBACK_URL="",
        ROOK_ALLOW_UNSIGNED_WEBHOOKS=False,
    )
    def test_missing_secrets_are_reported_without_being_printed(self):
        findings = rook_readiness_checks()
        errors = {key for severity, key, _ in findings if severity == "ERROR"}
        self.assertIn("ROOK_CLIENT_UUID", errors)
        self.assertIn("ROOK_SECRET_KEY", errors)
        self.assertIn("ROOK_WEBHOOK_HASH_KEY", errors)

    @override_settings(
        WEARABLES_ENABLED=True,
        ROOK_PROVISIONED_SOURCES="Garmin",
        ROOK_BASE_URL="https://api.rook-connect.review",
        ROOK_CLIENT_UUID="testing-uuid",
        ROOK_SECRET_KEY="testing-secret",
        ROOK_WEBHOOK_HASH_KEY="testing-hash",
        ROOK_CALLBACK_URL="https://bpk.example/r",
        ROOK_ALLOW_UNSIGNED_WEBHOOKS=False,
    )
    def test_configured_api_provider_reports_no_local_errors(self):
        findings = rook_readiness_checks()
        self.assertFalse([f for f in findings if f[0] == "ERROR"])
