"""ROOK-only operational settings; no changes to Biopeak's shared settings.

Quotas are hardcoded on Django settings modules (ROOK_API_REQUESTS_PER_*).
A missing or non-positive quota fails closed before any HTTP call.
"""
from decouple import config
from django.conf import settings

def setting(name: str, default=None):
    if hasattr(settings, name):
        return getattr(settings, name)
    return config(name, default=default)


def integer_setting(name: str, default: int, *, minimum: int, maximum: int):
    value = int(setting(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}.")
    return value


def enabled_setting(name: str, default: bool = False):
    value = setting(name, default)
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized not in {"true", "false", "1", "0"}:
        raise ValueError(f"{name} must be true or false.")
    return normalized in {"true", "1"}


def recovery_units_per_slice():
    return integer_setting("ROOK_SYNC_UNITS_PER_RUN", 3, minimum=1, maximum=21)


def request_limits():
    minute = integer_setting("ROOK_API_REQUESTS_PER_MINUTE", 0, minimum=0, maximum=100000)
    day = integer_setting("ROOK_API_REQUESTS_PER_DAY", 0, minimum=0, maximum=100000000)
    if not minute or not day:
        raise ValueError("Set approved ROOK_API_REQUESTS_PER_MINUTE and ROOK_API_REQUESTS_PER_DAY before enabling HTTP calls.")
    return minute, day
