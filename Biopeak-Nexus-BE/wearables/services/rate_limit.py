"""Cross-process ROOK budget using optimistic ORM updates, never network locks.

The deployment must allocate this budget within the actual contracted quota,
including any other applications using the same ROOK credentials.
"""
from datetime import timedelta
from hashlib import sha256

from django.db.models import F, Q
from django.utils import timezone

from wearables.models import RookRequestBudget
from wearables.services.provider_errors import RookConfigurationError, RookRequestDeferred
from wearables.services.rate_policy import budget_decision
from wearables.services.runtime import request_limits


def account_scope(base_url: str, client_uuid: str):
    # Stable non-secret identifier; credentials never appear in logs or keys.
    return sha256(f"{base_url.rstrip('/')}:{client_uuid}".encode()).hexdigest()


def reserve_provider_request(base_url: str, client_uuid: str):
    try:
        per_minute, per_day = request_limits()
    except ValueError as error:
        raise RookConfigurationError(str(error)) from error
    scope = account_scope(base_url, client_uuid)
    RookRequestBudget.objects.get_or_create(scope=scope)
    for _ in range(8):
        now = timezone.localtime()
        current = RookRequestBudget.objects.filter(scope=scope).first()
        decision = budget_decision(
            now=now, budget_date=current.budget_date, requests_today=current.requests_today,
            next_request_at=current.next_request_at, blocked_until=current.blocked_until,
            requests_per_minute=per_minute, requests_per_day=per_day,
        )
        if not decision["allowed"]:
            raise RookRequestDeferred(decision["retry_at"])
        changed = RookRequestBudget.objects.filter(scope=scope, revision=current.revision).update(
            revision=F("revision") + 1, budget_date=decision["budget_date"],
            requests_today=decision["requests_today"], next_request_at=decision["next_request_at"],
            updated_at=now,
        )
        if changed:
            return
    raise RookRequestDeferred(timezone.localtime() + timedelta(seconds=1), reason="budget_contention")


def block_provider_requests(base_url: str, client_uuid: str, retry_at):
    scope = account_scope(base_url, client_uuid)
    RookRequestBudget.objects.get_or_create(scope=scope)
    RookRequestBudget.objects.filter(scope=scope).filter(
        Q(blocked_until__isnull=True) | Q(blocked_until__lt=retry_at)
    ).update(blocked_until=retry_at, revision=F("revision") + 1, updated_at=timezone.localtime())
