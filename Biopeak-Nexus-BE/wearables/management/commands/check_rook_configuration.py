"""Inspect ROOK deployment readiness without printing secrets or contacting ROOK.

Run: uv run python manage.py check_rook_configuration --strict
This command cannot certify that provisioning or webhooks are enabled upstream.
"""
from urllib.parse import urlsplit

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from wearables.services.config import provisioned_sources
from wearables.utils.constants import NATIVE_WEARABLE_SOURCES, WearableSource


def validate_rook_callback(value: str) -> bool:
    """Confirm callback base URL can produce a valid short ROOK redirect."""
    if not value:
        return False
    parsed = urlsplit(value)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname
        and parsed.port is None
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and not parsed.query
        and parsed.path.rstrip("/") == "/r"
        and len(f"{value.rstrip('/')}/{'x' * 16}") <= 50
    )


def rook_readiness_checks() -> list[tuple[str, str, str]]:
    """Return (severity, setting name, advice), without any secret content."""
    checks: list[tuple[str, str, str]] = []
    if not getattr(settings, "WEARABLES_ENABLED", False):
        checks.append(("WARN", "WEARABLES_ENABLED", "Feature is disabled in this environment."))
    sources = provisioned_sources()
    if not sources:
        checks.append(("ERROR", "ROOK_PROVISIONED_SOURCES", "Set environment-prefixed provisioned provider names; ROOK must approve them."))
    else:
        approved_names = set(WearableSource.values)
        invalid = sources - approved_names
        if invalid:
            checks.append(("ERROR", "ROOK_PROVISIONED_SOURCES", "Unrecognized provider names. Use exact capitalization from /devices/providers/."))
        if "Strava" in sources:
            checks.append(("WARN", "ROOK_PROVISIONED_SOURCES", "Strava is not supported by the current ROOK authorizer route."))
        if any(source not in NATIVE_WEARABLE_SOURCES for source in sources):
            if not getattr(settings, "ROOK_CLIENT_UUID", ""):
                checks.append(("ERROR", "ROOK_CLIENT_UUID", "Missing ROOK API client UUID."))
            if not getattr(settings, "ROOK_SECRET_KEY", ""):
                checks.append(("ERROR", "ROOK_SECRET_KEY", "Missing ROOK API secret key."))
            callback = getattr(settings, "ROOK_CALLBACK_URL", "")
            if callback and not validate_rook_callback(callback):
                checks.append(("ERROR", "ROOK_CALLBACK_URL", "Expected short HTTPS URL ending in /r; full redirect with state token <= 50 characters."))
            if not callback:
                checks.append(("WARN", "ROOK_CALLBACK_URL", "No secure browser callback configured; authorization depends on authenticated device-status refresh."))
            if callback and validate_rook_callback(callback):
                checks.append(("INFO", "ROOK_CALLBACK_URL", "Valid URL format. Register it in ROOK and verify external HTTPS access."))
        if any(source in NATIVE_WEARABLE_SOURCES for source in sources):
            if not getattr(settings, "ROOK_SDK_CLIENT_UUID", "") or not getattr(settings, "ROOK_SDK_SECRET", ""):
                checks.append(("ERROR", "ROOK_SDK_CLIENT_UUID / ROOK_SDK_SECRET", "Native SDK provisioned but SDK credentials are missing."))
    if not getattr(settings, "ROOK_WEBHOOK_HASH_KEY", ""):
        checks.append(("ERROR", "ROOK_WEBHOOK_HASH_KEY", "Webhook hash key absent. Signed ingestion cannot be verified."))
    else:
        checks.append(("INFO", "ROOK_WEBHOOK_HASH_KEY", "Hash key present; ROOK dashboard delivery and signature must still be tested."))
    if getattr(settings, "ROOK_ALLOW_UNSIGNED_WEBHOOKS", False):
        checks.append(("ERROR", "ROOK_ALLOW_UNSIGNED_WEBHOOKS", "Disable unsigned webhooks before testing or production."))
    if not getattr(settings, "ROOK_BASE_URL", ""):
        checks.append(("ERROR", "ROOK_BASE_URL", "Missing upstream HTTPS API URL."))
    else:
        base = urlsplit(getattr(settings, "ROOK_BASE_URL", ""))
        if base.scheme != "https":
            checks.append(("ERROR", "ROOK_BASE_URL", "ROOK API URL must use HTTPS."))
    return checks


class Command(BaseCommand):
    help = "Check configuration readiness for ROOK without disclosing any credentials."

    def add_arguments(self, parser) -> None:
        parser.add_argument("--strict", action="store_true", help="Exit unsuccessfully when required configuration is absent.")

    def handle(self, *args, **options) -> None:
        checks = rook_readiness_checks()
        for severity, key, advice in checks:
            self.stdout.write(f"{severity}: {key}: {advice}")
        error_count = sum(item[0] == "ERROR" for item in checks)
        self.stdout.write(f"Summary: {error_count} configuration error(s). This is not a live ROOK connection test.")
        if options["strict"] and error_count:
            raise CommandError(f"ROOK deployment is not configured ({error_count} error(s)).")
