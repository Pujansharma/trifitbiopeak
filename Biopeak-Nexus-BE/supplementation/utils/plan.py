from collections.abc import Iterable
from datetime import date, datetime
from uuid import UUID

from supplementation.models import (
    Protocol,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
)
from supplementation.utils.constants import ProtocolItemTiming, ProtocolVersionStatus
from supplementation.utils.protocols import version_supplement_count
from supplementation.utils.version_status import LIVE_PROTOCOL_VERSION_STATUSES

PLAN_PROTOCOL_SUMMARY_STATUSES = (
    ProtocolVersionStatus.ACTIVE,
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.DRAFT,
    ProtocolVersionStatus.CANCELLED,
    ProtocolVersionStatus.EXPIRED,
)
PLAN_PROTOCOL_LIST_STATUSES = (
    ProtocolVersionStatus.ACTIVE,
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.CANCELLED,
    ProtocolVersionStatus.EXPIRED,
)
PLAN_LIVE_VERSION_RANK = {
    ProtocolVersionStatus.SCHEDULED: 0,
    ProtocolVersionStatus.ACTIVE: 1,
}
PLAN_CHANGE_STATUS_RANK = {
    ProtocolVersionStatus.ACTIVE: 0,
    ProtocolVersionStatus.SCHEDULED: 1,
}
PLAN_DOSING_FIELDS = (
    "dosage",
    "frequency",
    "custom_frequency",
    "timing",
    "instructions",
    "rationale",
)


def group_routine_items(items: Iterable[ProtocolItem]) -> list[dict[str, object]]:
    grouped = {timing: [] for timing in ProtocolItemTiming.values}
    for item in items:
        bucket = grouped.get(item.timing)
        if bucket is None:
            continue
        bucket.append(item)
    return [
        {"timing": timing, "items": grouped[timing]}
        for timing in ProtocolItemTiming.values
        if grouped[timing]
    ]


def plan_routine(
    items: Iterable[ProtocolItem],
) -> dict[str, list[dict[str, object]]]:
    return {"timings": group_routine_items(items)}


def prefetched_version(
    protocol: Protocol,
    version_pk: UUID | None,
) -> ProtocolVersion | None:
    if version_pk is None:
        return None
    for version in protocol.versions.all():
        if version.pk == version_pk:
            return version
    return None


def current_plan_version(protocol: Protocol) -> ProtocolVersion | None:
    current = protocol.current_version
    if current is None or not current.is_active:
        return None
    version = prefetched_version(protocol, current.pk)
    if version is None or not version.is_active:
        return None
    return version


def draft_version_count(protocol: Protocol) -> int:
    annotated_count = getattr(protocol, "draft_count", None)
    if annotated_count is not None:
        return annotated_count
    return sum(
        1
        for version in protocol.versions.all()
        if version.is_active and version.status == ProtocolVersionStatus.DRAFT
    )


def plan_protocol_summary_status(protocol: Protocol) -> str | None:
    version = current_plan_version(protocol)
    if version is not None and version.status in PLAN_PROTOCOL_SUMMARY_STATUSES:
        return version.status
    if version is not None or protocol.current_version is not None:
        return None
    if draft_version_count(protocol):
        return ProtocolVersionStatus.DRAFT
    return None


def plan_listed_protocol_sort_key(protocol: Protocol) -> tuple[date, datetime]:
    version = current_plan_version(protocol)
    if version is None:
        return (date.min, protocol.updated_at)
    return (version.starts_on or date.min, version.updated_at)


def plan_protocol_row(protocol: Protocol, version: ProtocolVersion) -> dict:
    return {
        "id": protocol.id,
        "name": protocol.name,
        "purpose": protocol.purpose,
        "status": version.status,
        "supplement_count": version_supplement_count(version),
        "version": {
            "id": version.id,
            "version_number": version.version_number,
            "starts_on": version.starts_on,
            "ends_on": version.ends_on,
        },
        "supplements": list(version.items.all()),
    }


def empty_plan_protocol_summary() -> dict[str, int]:
    return {
        ProtocolVersionStatus.ACTIVE: 0,
        ProtocolVersionStatus.SCHEDULED: 0,
        ProtocolVersionStatus.DRAFT: 0,
        ProtocolVersionStatus.CANCELLED: 0,
        ProtocolVersionStatus.EXPIRED: 0,
    }


def plan_protocols(protocols: Iterable[Protocol]) -> dict:
    summary = empty_plan_protocol_summary()
    listed = {status: [] for status in PLAN_PROTOCOL_LIST_STATUSES}
    for protocol in protocols:
        status = plan_protocol_summary_status(protocol)
        if status is None:
            continue
        summary[status] += 1
        if status not in listed:
            continue
        listed[status].append(protocol)
    payload = {"summary": summary}
    for status in PLAN_PROTOCOL_LIST_STATUSES:
        protocols = listed[status]
        protocols.sort(key=plan_listed_protocol_sort_key, reverse=True)
        payload[status] = [
            plan_protocol_row(protocol, current_plan_version(protocol))
            for protocol in protocols
        ]
    return payload


def plan_change_version_rank(version: ProtocolVersion) -> tuple[int, int]:
    return (PLAN_LIVE_VERSION_RANK[version.status], version.version_number)


def live_plan_version(protocol: Protocol) -> ProtocolVersion | None:
    candidates = [
        version
        for version in protocol.versions.all()
        if version.is_active and version.status in LIVE_PROTOCOL_VERSION_STATUSES
    ]
    if not candidates:
        return None
    return max(candidates, key=plan_change_version_rank)


def replace_events(version: ProtocolVersion) -> list[ProtocolEvent]:
    return list(version.replace_events)


def items_by_supplement(version: ProtocolVersion | None) -> dict[str, ProtocolItem]:
    if version is None:
        return {}
    return {str(item.supplement.pk): item for item in version.items.all()}


def snapshot_supplement_id(snapshot: object) -> str | None:
    if not isinstance(snapshot, dict):
        return None
    supplement_id = snapshot.get("supplement_id")
    if supplement_id is None:
        return None
    return str(supplement_id)


def supplement_identity(supplement) -> dict[str, str]:
    return {
        "id": str(supplement.id),
        "product_name": supplement.product_name,
        "brand_name": supplement.brand.name,
        "form": supplement.form,
    }


def dosing_payload(item: ProtocolItem) -> dict:
    return {field_name: getattr(item, field_name) for field_name in PLAN_DOSING_FIELDS}


def supplement_snapshot(item: ProtocolItem) -> dict:
    payload = {"supplement": supplement_identity(item.supplement)}
    payload.update(dosing_payload(item))
    return payload


def snapshot_sort_key(snapshot: dict) -> tuple[str, str]:
    supplement = snapshot["supplement"]
    return (supplement["product_name"].casefold(), supplement["id"])


def modified_change_sort_key(change: dict) -> tuple[str, str]:
    supplement = change["supplement"]
    return (supplement["product_name"].casefold(), supplement["id"])


def replaced_change_sort_key(change: dict) -> tuple[str, str]:
    supplement = change["after"]["supplement"]
    return (supplement["product_name"].casefold(), supplement["id"])


def modified_changes(
    previous_items: dict[str, ProtocolItem],
    live_items: dict[str, ProtocolItem],
) -> list[dict]:
    changes = []
    for supplement_id, live_item in live_items.items():
        previous_item = previous_items.get(supplement_id)
        if previous_item is None:
            continue
        if dosing_payload(previous_item) == dosing_payload(live_item):
            continue
        changes.append(
            {
                "supplement": supplement_identity(live_item.supplement),
                "before": dosing_payload(previous_item),
                "after": dosing_payload(live_item),
            }
        )
    changes.sort(key=modified_change_sort_key)
    return changes


def replace_pairs(
    events: list[ProtocolEvent],
    removed_ids: set[str],
    added_ids: set[str],
    previous_items: dict[str, ProtocolItem],
    live_items: dict[str, ProtocolItem],
) -> tuple[list[dict], set[str], set[str]]:
    consumed_removed: set[str] = set()
    consumed_added: set[str] = set()
    pairs = []
    for event in events:
        before_id = snapshot_supplement_id(event.before)
        after_id = snapshot_supplement_id(event.after)
        if before_id is None or after_id is None:
            continue
        if before_id not in removed_ids or after_id not in added_ids:
            continue
        if before_id in consumed_removed or after_id in consumed_added:
            continue
        consumed_removed.add(before_id)
        consumed_added.add(after_id)
        pairs.append(
            {
                "before": supplement_snapshot(previous_items[before_id]),
                "after": supplement_snapshot(live_items[after_id]),
            }
        )
    pairs.sort(key=replaced_change_sort_key)
    return pairs, consumed_removed, consumed_added


def leftover_snapshots(
    item_map: dict[str, ProtocolItem],
    candidate_ids: set[str],
    consumed_ids: set[str],
) -> list[dict]:
    rows = [
        supplement_snapshot(item_map[supplement_id])
        for supplement_id in candidate_ids
        if supplement_id not in consumed_ids
    ]
    rows.sort(key=snapshot_sort_key)
    return rows


def plan_supplement_change_row(protocol: Protocol, version: ProtocolVersion) -> dict:
    previous_pk = None
    if version.supersedes is not None:
        previous_pk = version.supersedes.pk
    previous = prefetched_version(protocol, previous_pk)
    previous_items = items_by_supplement(previous)
    live_items = items_by_supplement(version)
    removed_ids = set(previous_items) - set(live_items)
    added_ids = set(live_items) - set(previous_items)
    pairs, consumed_removed, consumed_added = replace_pairs(
        replace_events(version),
        removed_ids,
        added_ids,
        previous_items,
        live_items,
    )
    return {
        "name": protocol.name,
        "status": version.status,
        "changes": {
            "modified": modified_changes(previous_items, live_items),
            "replaced": pairs,
            "added": leftover_snapshots(live_items, added_ids, consumed_added),
            "removed": leftover_snapshots(
                previous_items,
                removed_ids,
                consumed_removed,
            ),
        },
    }


def plan_change_row_sort_key(row: dict) -> tuple[int, str]:
    return (PLAN_CHANGE_STATUS_RANK[row["status"]], row["name"].casefold())


def plan_supplement_changes(protocols: Iterable[Protocol]) -> list[dict]:
    rows = []
    for protocol in protocols:
        version = live_plan_version(protocol)
        if version is None:
            continue
        rows.append(plan_supplement_change_row(protocol, version))
    rows.sort(key=plan_change_row_sort_key)
    return rows
