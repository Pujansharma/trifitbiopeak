"""Additional ROOK V1 feature controls without modifying legacy settings files.

These opt-in controls may be supplied directly as Django settings or through
ordinary deployment environment variables. Do not put ROOK secrets in this file.
"""
import os
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
        value = os.environ.get("ROOK_PROVISIONED_SOURCES")
    if value is None:
        return None
    if isinstance(value, str):
        value = value.split(",")
    return {str(item).strip() for item in value if str(item).strip()}
