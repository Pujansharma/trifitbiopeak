"""Pure synchronization admission policy, independently testable without Django."""
from datetime import datetime, timedelta, timezone

MANUAL_SYNC_COOLDOWN = timedelta(hours=6)


def next_manual_sync_at(last_accepted_at: datetime | None):
    if last_accepted_at is None:
        return None
    if last_accepted_at.tzinfo is None:
        raise ValueError("Manual sync timestamps must include a timezone.")
    return last_accepted_at.astimezone(timezone.utc) + MANUAL_SYNC_COOLDOWN


def manual_sync_allowed(*, now: datetime, last_accepted_at: datetime | None):
    if now.tzinfo is None:
        raise ValueError("Manual sync timestamps must include a timezone.")
    next_allowed = next_manual_sync_at(last_accepted_at)
    return next_allowed is None or now >= next_allowed


class ManualSyncCooldown(ValueError):
    def __init__(self, next_allowed_at: datetime, job_id=None):
        super().__init__("A manual synchronization request was accepted within the last six hours.")
        self.next_allowed_at = next_allowed_at
        self.job_id = job_id
