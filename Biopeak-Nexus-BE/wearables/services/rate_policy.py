"""Pure account-budget calculations; datetime inputs must be aware instants."""
from datetime import datetime, time, timedelta, timezone
from email.utils import parsedate_to_datetime
import math


def retry_after_time(value: str | None, *, now: datetime):
    if now.tzinfo is None:
        raise ValueError("Rate-limit timestamps must be aware.")
    now = now.astimezone(timezone.utc)
    text = str(value or "").strip()
    if text.isdigit():
        # Clamp untrusted input only to a finite protective upper bound.
        return now + timedelta(seconds=min(max(int(text), 1), 7 * 86400))
    if text:
        try:
            parsed = parsedate_to_datetime(text)
        except (ValueError, TypeError, OverflowError):
            parsed = None
        if parsed is not None:
            parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            return max(now + timedelta(seconds=1), parsed)
    return now + timedelta(seconds=60)


def budget_decision(*, now: datetime, budget_date, requests_today: int,
                    next_request_at, blocked_until, requests_per_minute: int,
                    requests_per_day: int):
    if now.tzinfo is None or requests_per_minute <= 0 or requests_per_day <= 0:
        raise ValueError("Aware time and positive approved provider budgets are required.")
    now = now.astimezone(timezone.utc)
    today = now.date()
    count = requests_today if budget_date == today else 0
    waits = [value for value in (next_request_at, blocked_until) if value is not None and value > now]
    if count >= requests_per_day:
        waits.append(datetime.combine(today + timedelta(days=1), time.min, tzinfo=timezone.utc))
    if waits:
        return {"allowed": False, "retry_at": max(waits)}
    return {"allowed": True, "budget_date": today, "requests_today": count + 1,
            "next_request_at": now + timedelta(seconds=60 / requests_per_minute)}


def seconds_until(retry_at: datetime, now: datetime):
    return max(1, math.ceil((retry_at - now).total_seconds()))
