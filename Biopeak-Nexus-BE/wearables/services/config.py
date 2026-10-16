"""Additional ROOK V1 feature controls without modifying legacy settings files.

These opt-in controls may be supplied directly as Django settings or through
ordinary deployment environment variables. Do not put ROOK secrets in this file.
"""
import os
from decouple import config
from django.conf import settings


def preexisting_import_enabled() -> bool:
    value = getattr(settings, "ROOK_PREEXISTING_ENABLED", None)
    if value is None:
        value = os.environ.get("ROOK_PREEXISTING_ENABLED")
    if value is None or value == "":
        return getattr(settings, "ROOK_ENVIRONMENT", "production").lower() != "production"
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "on", "yes"}


def provisioned_sources() -> set[str] | None:
    """None means not yet reviewed, not that all providers are provisioned."""
    value = getattr(settings, "ROOK_PROVISIONED_SOURCES", None)
    if value is None:
        # Settings can be supplied as an actual process environment variable,
        # or in the project's python-decouple .env with the same environment
        # prefix as the other ROOK credentials. Keep provisioning fail-closed.
        value = config("ROOK_PROVISIONED_SOURCES", default=None)
    if value is None:
        environment = os.environ.get("DJANGO_SETTINGS_MODULE", "").rsplit(".", 1)[-1]
        prefix = {"development": "DEV_", "staging": "STG_", "production": "PRD_"}.get(environment, "")
        if prefix:
            value = config(f"{prefix}ROOK_PROVISIONED_SOURCES", default=None)
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split(",")
    return {str(item).strip() for item in value if str(item).strip()}
