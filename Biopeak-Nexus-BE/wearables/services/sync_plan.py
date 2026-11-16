"""Pure, date-based sync planning shared by the manager's three sync triggers.

No network, database, Django or user credentials. Inclusive local dates match
ROOK's date-based summary endpoint. The upper timestamp is frozen at enqueue.
"""
from datetime import date, datetime, timedelta
from typing import Iterator
from zoneinfo import ZoneInfo

HEALTH_PILLARS = ("physical", "sleep", "body")
INITIAL_HISTORY_DAYS = 7


def create_sync_plan(*, requested_at: datetime, timezone_name: str,
                     previous_cursor: datetime | None, flow: str,
                     initial_days: int = INITIAL_HISTORY_DAYS) -> dict:
    if requested_at.tzinfo is None or (previous_cursor is not None and previous_cursor.tzinfo is None):
        raise ValueError("Sync timestamps must be timezone-aware.")
    member_timezone = ZoneInfo(timezone_name)
    end_date = requested_at.astimezone(member_timezone).date()
    if flow == "rolling":
        start_date = end_date - timedelta(days=6)
    elif flow == "initial" or previous_cursor is None:
        start_date = end_date - timedelta(days=max(1, min(initial_days, 7)) - 1)
    else:
        # Recheck the last covered LOCAL day; later source corrections can
        # change that day's version. Ingestion deduplicates stored documents.
        start_date = min(previous_cursor.astimezone(member_timezone).date(), end_date)
    return {
        "flow": flow, "startDate": start_date.isoformat(),
        "endDate": end_date.isoformat(), "windowEnd": requested_at.isoformat(),
        "nextDate": start_date.isoformat(), "nextPillar": 0,
        "requestCount": 0, "documentCount": 0,
        "timezone": timezone_name,
    }


def remaining_sync_units(plan: dict) -> Iterator[tuple[str, str]]:
    current = date.fromisoformat(plan["nextDate"])
    end_date = date.fromisoformat(plan["endDate"])
    first_pillar = int(plan.get("nextPillar", 0))
    if first_pillar not in range(len(HEALTH_PILLARS)):
        raise ValueError("Invalid saved health pillar checkpoint.")
    while current <= end_date:
        for pillar in HEALTH_PILLARS[first_pillar:]:
            yield current.isoformat(), pillar
        current += timedelta(days=1)
        first_pillar = 0


def advance_sync_plan(plan: dict, *, summary_date: str, pillar: str,
                      document_count: int) -> dict:
    expected = next(remaining_sync_units(plan), None)
    if expected != (summary_date, pillar):
        raise ValueError("Cannot advance over an unprocessed date/category checkpoint.")
    if document_count < 0:
        raise ValueError("Document count cannot be negative.")
    next_pillar = HEALTH_PILLARS.index(pillar) + 1
    next_date = date.fromisoformat(summary_date)
    if next_pillar == len(HEALTH_PILLARS):
        next_pillar = 0
        next_date += timedelta(days=1)
    return {
        **plan, "nextDate": next_date.isoformat(), "nextPillar": next_pillar,
        "requestCount": int(plan.get("requestCount", 0)) + 1,
        "documentCount": int(plan.get("documentCount", 0)) + document_count,
    }


def sync_plan_complete(plan: dict) -> bool:
    return date.fromisoformat(plan["nextDate"]) > date.fromisoformat(plan["endDate"])
