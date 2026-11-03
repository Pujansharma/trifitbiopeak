from collections.abc import Iterable
from datetime import date, datetime

from django.db.models import Count, Q, QuerySet

from supplementation.models import Protocol, ProtocolVersion
from supplementation.utils.constants import ProtocolVersionStatus

ACTIVE_BUCKET = "active"
COMING_UP_BUCKET = "coming_up"
PREPARING_BUCKET = "preparing"
HISTORICAL_BUCKET = "historical"

STORED_HISTORICAL_STATUSES = frozenset(
    {
        ProtocolVersionStatus.SUPERSEDED,
        ProtocolVersionStatus.EXPIRED,
        ProtocolVersionStatus.CANCELLED,
    }
)
WINDOW_STATUSES = frozenset(
    {
        ProtocolVersionStatus.ACTIVE,
        ProtocolVersionStatus.SCHEDULED,
    }
)
PREPARING_STATUSES = frozenset(
    {
        ProtocolVersionStatus.APPROVED,
        ProtocolVersionStatus.DRAFT,
    }
)


def protocol_version_bucket(
    version: ProtocolVersion | None,
    today: date,
) -> str | None:
    if version is None or not version.is_active:
        return None
    ended = version.ends_on is not None and version.ends_on < today
    status = version.status
    if status in STORED_HISTORICAL_STATUSES or (status in WINDOW_STATUSES and ended):
        return HISTORICAL_BUCKET
    if (
        status == ProtocolVersionStatus.SCHEDULED
        and version.starts_on is not None
        and version.starts_on > today
    ):
        return COMING_UP_BUCKET
    scheduled_started = (
        status == ProtocolVersionStatus.SCHEDULED
        and version.starts_on is not None
        and version.starts_on <= today
        and not ended
    )
    stored_active = status == ProtocolVersionStatus.ACTIVE and not ended
    if stored_active or scheduled_started:
        return ACTIVE_BUCKET
    if status in PREPARING_STATUSES:
        return PREPARING_BUCKET
    return None


def annotate_draft_count(
    protocols: QuerySet[Protocol] | Iterable[Protocol],
) -> QuerySet[Protocol] | Iterable[Protocol]:
    if not hasattr(protocols, "annotate"):
        return protocols
    if "draft_count" in protocols.query.annotations:
        return protocols
    return protocols.annotate(
        draft_count=Count(
            "versions",
            filter=Q(
                versions__is_active=True,
                versions__status=ProtocolVersionStatus.DRAFT,
            ),
        )
    )


def current_version_is_missing(protocol: Protocol) -> bool:
    version = protocol.current_version
    return version is None or not version.is_active


def protocol_has_active_draft(protocol: Protocol) -> bool:
    annotated_count = getattr(protocol, "draft_count", None)
    if annotated_count is not None:
        return annotated_count > 0
    return protocol.versions.filter(
        is_active=True,
        status=ProtocolVersionStatus.DRAFT,
    ).exists()


def summary_protocol_bucket(protocol: Protocol, today: date) -> str | None:
    bucket = protocol_version_bucket(protocol.current_version, today)
    if bucket is not None:
        return bucket
    if current_version_is_missing(protocol) and protocol_has_active_draft(protocol):
        return PREPARING_BUCKET
    return None


def active_version_sort_key(version: ProtocolVersion) -> tuple[date, datetime]:
    return (version.starts_on or date.min, version.updated_at)


def active_protocol_sort_key(protocol: Protocol) -> tuple[date, datetime]:
    version = protocol.current_version
    if version is None:
        return (date.min, protocol.updated_at)
    return active_version_sort_key(version)


def group_current_protocols(protocols, today: date) -> dict[str, list[Protocol]]:
    grouped: dict[str, list[Protocol]] = {
        ACTIVE_BUCKET: [],
        COMING_UP_BUCKET: [],
        PREPARING_BUCKET: [],
        HISTORICAL_BUCKET: [],
    }
    for protocol in protocols:
        if not protocol.is_active:
            continue
        bucket = summary_protocol_bucket(protocol, today)
        if bucket is None:
            continue
        grouped[bucket].append(protocol)
    for protocols_in_bucket in grouped.values():
        protocols_in_bucket.sort(key=active_protocol_sort_key, reverse=True)
    return grouped


def protocol_status_counts(protocols, today: date) -> dict[str, int]:
    grouped = group_current_protocols(annotate_draft_count(protocols), today)
    return {
        ACTIVE_BUCKET: len(grouped[ACTIVE_BUCKET]),
        COMING_UP_BUCKET: len(grouped[COMING_UP_BUCKET]),
        PREPARING_BUCKET: len(grouped[PREPARING_BUCKET]),
        HISTORICAL_BUCKET: len(grouped[HISTORICAL_BUCKET]),
    }


def version_supplement_count(version: ProtocolVersion) -> int:
    annotated_count = getattr(version, "supplement_count", None)
    if annotated_count is None:
        return version.items.count()
    return annotated_count


def summarize_current_protocols(
    protocols,
    today: date,
) -> tuple[Protocol | None, int, int]:
    active_protocols: list[Protocol] = []
    coming_up_count = 0
    historical_counts = 0
    for protocol in protocols:
        if not protocol.is_active:
            continue
        bucket = protocol_version_bucket(protocol.current_version, today)
        if bucket == ACTIVE_BUCKET:
            active_protocols.append(protocol)
        elif bucket == COMING_UP_BUCKET:
            coming_up_count += 1
        elif bucket == HISTORICAL_BUCKET:
            historical_counts += 1
    if not active_protocols:
        return None, coming_up_count, historical_counts
    active_protocol = max(active_protocols, key=active_protocol_sort_key)
    return active_protocol, coming_up_count, historical_counts
