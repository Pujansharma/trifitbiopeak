from datetime import date, timedelta
from operator import attrgetter

from django.db import IntegrityError, transaction
from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from supplementation.models import Protocol, ProtocolVersion
from supplementation.utils.constants import ProtocolVersionStatus

PROTOCOL_VERSION_DEFAULT_DURATION_DAYS = 90
PROTOCOL_SWEEP_CHUNK = 100
PROTOCOL_ONE_ACTIVE_CONSTRAINT = "uniq_protocol_one_active"
LIVE_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.ACTIVE,
)
LISTED_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.APPROVED,
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.ACTIVE,
    ProtocolVersionStatus.EXPIRED,
    ProtocolVersionStatus.CANCELLED,
)
UNFINISHED_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.DRAFT,
    ProtocolVersionStatus.UNDER_REVIEW,
)


def accept_listed_protocol_version(
    version: ProtocolVersion,
    has_newer_draft_or_review: bool,
) -> ProtocolVersion | None:
    return version


def accept_superseded_listed_protocol_version(
    version: ProtocolVersion,
    has_newer_draft_or_review: bool,
) -> ProtocolVersion | None:
    if has_newer_draft_or_review:
        return version
    return None


def skip_listed_protocol_version(
    version: ProtocolVersion,
    has_newer_draft_or_review: bool,
) -> ProtocolVersion | None:
    return None


LISTED_PROTOCOL_VERSION_RULES = {
    status: accept_listed_protocol_version
    for status in LISTED_PROTOCOL_VERSION_STATUSES
} | {
    ProtocolVersionStatus.SUPERSEDED: accept_superseded_listed_protocol_version,
    ProtocolVersionStatus.DRAFT: skip_listed_protocol_version,
    ProtocolVersionStatus.UNDER_REVIEW: skip_listed_protocol_version,
}


def default_protocol_ends_on(starts_on: date):
    return starts_on + timedelta(days=PROTOCOL_VERSION_DEFAULT_DURATION_DAYS)


def published_status(starts_on: date, today: date):
    if starts_on > today:
        return ProtocolVersionStatus.SCHEDULED
    return ProtocolVersionStatus.ACTIVE


def is_protocol_one_active_violation(error: IntegrityError):
    return PROTOCOL_ONE_ACTIVE_CONSTRAINT in str(error)


def expire_protocol_versions(today: date):
    return ProtocolVersion.objects.filter(
        status__in=LIVE_PROTOCOL_VERSION_STATUSES,
        ends_on__lt=today,
    ).update(status=ProtocolVersionStatus.EXPIRED, updated_at=timezone.localtime())


def due_scheduled_versions(today: date):
    return (
        ProtocolVersion.objects.filter(
            status=ProtocolVersionStatus.SCHEDULED,
            starts_on__lte=today,
        )
        .filter(Q(ends_on__isnull=True) | Q(ends_on__gte=today))
        .select_related("protocol__current_version")
    )


def due_protocol_pks(today: date):
    return (
        due_scheduled_versions(today)
        .order_by()
        .values_list("protocol", flat=True)
        .distinct()
    )


def higher_protocol_versions():
    return ProtocolVersion.objects.filter(
        protocol=OuterRef("protocol"),
        version_number__gt=OuterRef("version_number"),
    )


def listed_protocol_versions():
    blocked_higher_versions = higher_protocol_versions().exclude(
        status__in=UNFINISHED_PROTOCOL_VERSION_STATUSES,
    )
    return ProtocolVersion.objects.filter(
        Q(status__in=LISTED_PROTOCOL_VERSION_STATUSES)
        | (
            Q(status=ProtocolVersionStatus.SUPERSEDED)
            & Exists(higher_protocol_versions())
            & ~Exists(blocked_higher_versions)
        )
    )


def select_listed_protocol_version(
    versions: list[ProtocolVersion],
) -> ProtocolVersion | None:
    has_newer_draft_or_review = False
    ordered_versions = sorted(
        versions,
        key=attrgetter("version_number"),
        reverse=True,
    )
    for version in ordered_versions:
        selected = LISTED_PROTOCOL_VERSION_RULES[version.status](
            version,
            has_newer_draft_or_review,
        )
        if version.status in UNFINISHED_PROTOCOL_VERSION_STATUSES:
            has_newer_draft_or_review = True
        if selected is not None:
            return selected
    return None


def version_to_activate(versions: list[ProtocolVersion]):
    current = versions[0].protocol.current_version
    if current is not None:
        for version in versions:
            if version.pk == current.pk:
                return version
    return max(versions, key=attrgetter("version_number"))


def commit_protocol_activation(versions: list[ProtocolVersion]):
    chosen = version_to_activate(versions)
    now = timezone.localtime()
    other_pks = [version.pk for version in versions if version.pk != chosen.pk]
    with transaction.atomic():
        if other_pks:
            ProtocolVersion.objects.filter(
                pk__in=other_pks,
                status=ProtocolVersionStatus.SCHEDULED,
            ).update(
                status=ProtocolVersionStatus.SUPERSEDED,
                updated_at=now,
            )
        updated = ProtocolVersion.objects.filter(
            pk=chosen.pk,
            status=ProtocolVersionStatus.SCHEDULED,
        ).update(status=ProtocolVersionStatus.ACTIVE, updated_at=now)
        if updated == 0:
            transaction.set_rollback(True)
            return 0
        Protocol.objects.filter(pk=chosen.protocol.pk).update(
            current_version=chosen,
            updated_at=now,
        )
    return 1


def activate_protocol_versions(versions: list[ProtocolVersion]):
    try:
        return commit_protocol_activation(versions)
    except IntegrityError as error:
        if not is_protocol_one_active_violation(error):
            raise
        return 0


def activate_protocol_chunk(protocol_pks: list, today: date):
    grouped: dict = {}
    versions = due_scheduled_versions(today).filter(protocol__in=protocol_pks)
    for version in versions:
        grouped.setdefault(version.protocol.pk, []).append(version)
    activated = 0
    for protocol_versions in grouped.values():
        activated += activate_protocol_versions(protocol_versions)
    return activated


def activate_due_protocol_versions(today: date):
    protocol_pks = list(due_protocol_pks(today))
    activated = 0
    for start in range(0, len(protocol_pks), PROTOCOL_SWEEP_CHUNK):
        chunk = protocol_pks[start : start + PROTOCOL_SWEEP_CHUNK]
        activated += activate_protocol_chunk(chunk, today)
    return activated


def sweep_protocol_versions(today: date | None = None):
    if today is None:
        today = timezone.localdate()
    expired_count = expire_protocol_versions(today)
    activated_count = activate_due_protocol_versions(today)
    return expired_count, activated_count
