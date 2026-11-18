"""Per-document contributions that let daily summaries be corrected without observation rows.

Each HealthDailySummary row keeps one entry in ``contributions`` for every canonical
ROOK document (keyed by its document identity) that contributed to that day/metric/source.
An entry holds only the aggregates that one document produced, so a correction or a
timezone remap can replace or move exactly that document's share. The row's count,
minimum, maximum, average, total and latest are always derived from the entries that
remain, so nothing is fabricated and superseded values disappear.

Entry keys (kept short because they are stored per row):
    v   document version that produced the entry
    u   unit
    n   number of numeric values
    s   sum of numeric values
    mn  minimum numeric value
    mx  maximum numeric value
    lv  latest numeric value (last one extracted from the document)
    tv  latest text or boolean value (non-numeric metrics; n stays 0)
    at  document observed_at, ISO-8601 UTC
    ds  data sources (list)
    cf  confidence (1.0 default, 0.5 after a source change)
    sc  source-change details {from, to, at} when the source changed
    cr  clinical review suggested (extreme reported heart rate)
"""

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from wearables.models import HealthDailySummary

CLINICAL_REVIEW_HEART_RATE_METRICS = frozenset({"average_heart_rate", "resting_heart_rate", "maximum_heart_rate"})
CLINICAL_REVIEW_THRESHOLD = 220


def member_zone(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def local_date_for(observed_at: datetime, timezone_name: str) -> date:
    return observed_at.astimezone(member_zone(timezone_name)).date()


def _at(entry: dict) -> datetime:
    return datetime.fromisoformat(entry["at"]).astimezone(UTC)


def new_entry(*, version: int, unit: str, observed_at: datetime, data_sources: list[str],
              confidence: float = 1.0) -> dict:
    return {
        "v": version,
        "u": unit,
        "n": 0,
        "s": 0.0,
        "at": observed_at.astimezone(UTC).isoformat(),
        "ds": list(data_sources),
        "cf": confidence,
    }


def add_value(entry: dict, value) -> None:
    """Fold one extracted value into a document-level entry."""
    if isinstance(value, bool):
        entry["tv"] = value
        return
    if isinstance(value, (int, float)):
        number = float(value)
        entry["n"] += 1
        entry["s"] += number
        entry["mn"] = number if "mn" not in entry else min(entry["mn"], number)
        entry["mx"] = number if "mx" not in entry else max(entry["mx"], number)
        entry["lv"] = number
        return
    entry["tv"] = str(value)[:512]


def mark_clinical_review(entry: dict, metric: str, value) -> None:
    if (metric in CLINICAL_REVIEW_HEART_RATE_METRICS and isinstance(value, (int, float))
            and not isinstance(value, bool) and value >= CLINICAL_REVIEW_THRESHOLD):
        entry["cr"] = True


def summarize(contributions: dict) -> dict:
    """Derive every aggregate column from the entries that remain for one row."""
    entries = list(contributions.values())
    numeric = [entry for entry in entries if entry.get("n")]
    count = sum(entry["n"] for entry in numeric)
    total = sum(entry["s"] for entry in numeric) if numeric else None
    latest_numeric = max(numeric, key=_at) if numeric else None
    last_entry = max(entries, key=_at)
    first_entry = min(entries, key=_at)
    sources = sorted({source for entry in entries for source in entry.get("ds", [])})
    return {
        "count": count,
        "minimum": min((entry["mn"] for entry in numeric), default=None),
        "maximum": max((entry["mx"] for entry in numeric), default=None),
        "average": total / count if count else None,
        "total": total,
        "latest": latest_numeric["lv"] if latest_numeric else None,
        "unit": last_entry.get("u", ""),
        "first_observed_at": _at(first_entry),
        "last_observed_at": _at(last_entry),
        "data_sources": sources,
    }


def refresh_row(row: HealthDailySummary) -> bool:
    """Recompute a row's aggregates from its entries. Returns False when no entries remain."""
    if not row.contributions:
        return False
    for field, value in summarize(row.contributions).items():
        setattr(row, field, value)
    row.completeness = 1.0
    return True


def recompute_or_delete(row: HealthDailySummary) -> None:
    if refresh_row(row):
        row.save()
    else:
        row.delete()


def upsert_contributions(*, customer_profile, domain: str, metric: str, local_date: date,
                         source_key: str, entries: dict) -> HealthDailySummary:
    """Add or replace several documents' entries in one row, with one write."""
    first = next(iter(entries.values()), {})
    row, _ = HealthDailySummary.objects.get_or_create(
        customer_profile=customer_profile,
        domain=domain,
        metric=metric,
        local_date=local_date,
        source_key=source_key,
        defaults={"unit": first.get("u", "")},
    )
    row.contributions = {**row.contributions, **entries}
    refresh_row(row)
    row.save()
    return row


def upsert_contribution(*, customer_profile, domain: str, metric: str, local_date: date,
                        source_key: str, identity_key: str, entry: dict) -> HealthDailySummary:
    return upsert_contributions(
        customer_profile=customer_profile, domain=domain, metric=metric, local_date=local_date,
        source_key=source_key, entries={identity_key: entry},
    )


def drop_contribution(row: HealthDailySummary, identity_key: str) -> None:
    row.contributions = {key: value for key, value in row.contributions.items() if key != identity_key}
    recompute_or_delete(row)


def prior_summary_row(customer_profile, *, domain: str, metric: str, observed_at: datetime):
    """Latest stored row for this metric at or before the instant, used for source-change detection."""
    return (
        HealthDailySummary.objects.filter(
            customer_profile=customer_profile,
            domain=domain,
            metric=metric,
            last_observed_at__lte=observed_at,
        )
        .order_by("-last_observed_at", "-created_at")
        .first()
    )


def latest_text_value(contributions: dict):
    """Latest non-numeric value (text or boolean) recorded for a row, or None."""
    texts = [entry for entry in contributions.values() if "tv" in entry]
    if not texts:
        return None
    return max(texts, key=_at)["tv"]


def contribution_confidence(contributions: dict) -> float:
    return min((entry.get("cf", 1.0) for entry in contributions.values()), default=1.0)


def contribution_source_change(contributions: dict) -> dict | None:
    changed = [entry for entry in contributions.values() if entry.get("sc")]
    if not changed:
        return None
    return max(changed, key=_at)["sc"]


def contribution_max_version(contributions: dict) -> int | None:
    return max((entry["v"] for entry in contributions.values() if "v" in entry), default=None)


def contribution_clinical_review(contributions: dict) -> bool:
    return any(entry.get("cr") for entry in contributions.values())
