"""Allowlisted synthetic phone identities for isolated dev/staging smoke tests."""

from django.conf import settings


TEST_LOGIN_CONTACTS = tuple(
    (
        f"+91-99999001{account_number:02d}",
        f"biopeak-direct-test-{account_number:02d}@example.com",
    )
    for account_number in range(1, 9)
)
TEST_LOGIN_EMAIL_BY_PHONE = dict(TEST_LOGIN_CONTACTS)
TEST_LOGIN_SETTINGS_MODULES = frozenset(
    {"core.settings.development", "core.settings.staging"}
)


def direct_phone_login_testing_is_enabled() -> bool:
    """Allow local dev without a key; require a strong key for staging."""
    key = getattr(settings, "TEST_PHONE_LOGIN_KEY", "")
    return (
        settings.SETTINGS_MODULE in TEST_LOGIN_SETTINGS_MODULES
        and getattr(settings, "TEST_PHONE_LOGIN_ENABLED", False) is True
        and (
            settings.SETTINGS_MODULE == "core.settings.development"
            or (isinstance(key, str) and len(key) >= 32)
        )
    )
