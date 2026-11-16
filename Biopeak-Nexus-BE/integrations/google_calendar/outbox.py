from datetime import timedelta
from uuid import UUID

from django.db import IntegrityError
from django.db.models import F
from django.utils import timezone

from core.utils.log import logger
from integrations.google_calendar.dispatch import (
    delete_google_calendar_queue_message,
    google_calendar_outbox_queue_url,
    publish_google_calendar_job_batches,
)
from integrations.google_calendar.google_sync import (
    GOOGLE_SYNC_ERRORS,
    describe_google_error,
    is_google_calendar_configured,
    sync_appointment_with_google,
)
from integrations.google_calendar.personal_outbound import (
    sync_associate_blocks_to_personal_google,
    sync_associate_leave_to_personal_google,
)
from integrations.models import GoogleCalendarOutbox
from integrations.utils.constants import (
    CommunicationEventType,
    GoogleCalendarOutboxStatus,
    MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
    STALE_GOOGLE_CALENDAR_QUEUED_MINUTES,
    STALE_GOOGLE_CALENDAR_SENDING_MINUTES,
    TERMINAL_APPOINTMENT_EVENT_TYPES,
    TERMINAL_GOOGLE_OUTBOX_BLOCKING_STATUSES,
)
from integrations.utils.sqs_dispatch import chunk_job_ids

TERMINAL_EVENT_TYPES = TERMINAL_APPOINTMENT_EVENT_TYPES
ACTIVE_OUTBOX_STATUSES = TERMINAL_GOOGLE_OUTBOX_BLOCKING_STATUSES
OPEN_GOOGLE_OUTBOX_STATUSES = (
    GoogleCalendarOutboxStatus.PENDING,
    GoogleCalendarOutboxStatus.QUEUED,
    GoogleCalendarOutboxStatus.FAILED,
)
DISPATCHABLE_STATUSES = (
    GoogleCalendarOutboxStatus.PENDING,
    GoogleCalendarOutboxStatus.FAILED,
)
CLAIMABLE_STATUSES = (
    GoogleCalendarOutboxStatus.PENDING,
    GoogleCalendarOutboxStatus.QUEUED,
    GoogleCalendarOutboxStatus.FAILED,
)

RETRYABLE_GOOGLE_SKIP_REASONS = {
    "Google Calendar organizer is disconnected": "organizer_disconnected",
}


def existing_terminal_google_outbox(appointment, event_type):
    return (
        GoogleCalendarOutbox.objects.filter(
            appointment=appointment,
            event_type=event_type,
            status__in=ACTIVE_OUTBOX_STATUSES,
        )
        .order_by("-created_at")
        .first()
    )


def existing_open_google_outbox(appointment):
    return (
        GoogleCalendarOutbox.objects.filter(
            appointment=appointment,
            status__in=OPEN_GOOGLE_OUTBOX_STATUSES,
            attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
        )
        .order_by("created_at")
        .first()
    )


def create_google_outbox_message(
    appointment=None,
    *,
    event_type,
    status,
    skip_reason="",
    associate_availability_block=None,
    associate_leave=None,
    availability_series_id=None,
):
    try:
        return GoogleCalendarOutbox.objects.create(
            appointment=appointment,
            associate_availability_block=associate_availability_block,
            associate_leave=associate_leave,
            availability_series_id=availability_series_id,
            event_type=event_type,
            status=status,
            skip_reason=skip_reason,
        )
    except IntegrityError:
        if appointment is not None:
            existing = existing_terminal_google_outbox(appointment, event_type)
            if existing is not None:
                return existing
            raise
        existing = existing_open_google_availability_outbox(
            associate_availability_block=associate_availability_block,
            associate_leave=associate_leave,
            availability_series_id=availability_series_id,
        )
        if existing is not None:
            return existing
        raise


def google_outbox_target_filter(
    *,
    appointment_id=None,
    associate_availability_block_id=None,
    associate_leave_id=None,
    availability_series_id=None,
):
    if appointment_id is not None:
        return {"appointment_id": appointment_id}
    if availability_series_id is not None:
        return {"availability_series_id": availability_series_id}
    if associate_availability_block_id is not None:
        return {
            "associate_availability_block_id": associate_availability_block_id
        }
    if associate_leave_id is not None:
        return {"associate_leave_id": associate_leave_id}
    return None


def google_outbox_target_filter_for_message(message):
    return google_outbox_target_filter(
        appointment_id=message.appointment_id,
        associate_availability_block_id=message.associate_availability_block_id,
        associate_leave_id=message.associate_leave_id,
        availability_series_id=message.availability_series_id,
    )


def existing_open_google_availability_outbox(
    *,
    associate_availability_block=None,
    associate_leave=None,
    availability_series_id=None,
):
    filters = {
        "status__in": OPEN_GOOGLE_OUTBOX_STATUSES,
        "attempt_count__lt": MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
    }
    if availability_series_id is not None:
        filters["availability_series_id"] = availability_series_id
    elif associate_availability_block is not None:
        filters["associate_availability_block"] = associate_availability_block
    elif associate_leave is not None:
        filters["associate_leave"] = associate_leave
    else:
        return None
    return (
        GoogleCalendarOutbox.objects.filter(**filters)
        .order_by("created_at")
        .first()
    )


def enqueue_associate_block_sync(*, block=None, series_id=None, wake=True):
    existing = existing_open_google_availability_outbox(
        associate_availability_block=block if series_id is None else None,
        availability_series_id=series_id,
    )
    if existing is not None:
        message = existing
    else:
        message = create_google_outbox_message(
            event_type=CommunicationEventType.ASSOCIATE_BLOCK_SYNC,
            status=GoogleCalendarOutboxStatus.PENDING,
            associate_availability_block=block if series_id is None else None,
            availability_series_id=series_id,
        )
    if wake:
        dispatch_if_claimable(message)
    return message


def enqueue_associate_leave_sync(leave, *, wake=True):
    existing = existing_open_google_availability_outbox(associate_leave=leave)
    if existing is not None:
        message = existing
    else:
        message = create_google_outbox_message(
            event_type=CommunicationEventType.ASSOCIATE_LEAVE_SYNC,
            status=GoogleCalendarOutboxStatus.PENDING,
            associate_leave=leave,
        )
    if wake:
        dispatch_if_claimable(message)
    return message


def enqueue_google_calendar_message(appointment, event_type, *, wake=True):
    if not is_google_calendar_configured():
        return create_google_outbox_message(
            appointment,
            event_type=event_type,
            status=GoogleCalendarOutboxStatus.SKIPPED,
            skip_reason="Google Calendar is not configured",
        )

    existing = existing_open_google_outbox(appointment)
    if existing is not None:
        message = existing
    elif event_type in TERMINAL_EVENT_TYPES:
        existing_terminal = existing_terminal_google_outbox(appointment, event_type)
        if existing_terminal is not None:
            message = existing_terminal
        else:
            message = create_google_outbox_message(
                appointment,
                event_type=event_type,
                status=GoogleCalendarOutboxStatus.PENDING,
            )
    else:
        message = create_google_outbox_message(
            appointment,
            event_type=event_type,
            status=GoogleCalendarOutboxStatus.PENDING,
        )
    if wake:
        dispatch_if_claimable(message)
    return message


def mark_google_calendar_jobs_queued(job_ids: list[UUID]) -> list[UUID]:
    now = timezone.localtime()
    marked = []
    for job_id in job_ids:
        updated = GoogleCalendarOutbox.objects.filter(
            pk=job_id,
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
        ).update(
            status=GoogleCalendarOutboxStatus.QUEUED,
            updated_at=now,
        )
        if updated == 1:
            marked.append(job_id)
    return marked


def revert_google_calendar_jobs_to_pending(job_ids: list[UUID]) -> int:
    if not job_ids:
        return 0
    now = timezone.localtime()
    return GoogleCalendarOutbox.objects.filter(
        pk__in=job_ids,
        status=GoogleCalendarOutboxStatus.QUEUED,
    ).update(
        status=GoogleCalendarOutboxStatus.PENDING,
        updated_at=now,
    )


def dispatch_google_calendar_job_ids(job_ids: list[UUID]) -> int:
    if not google_calendar_outbox_queue_url():
        return 0
    marked_ids = mark_google_calendar_jobs_queued(job_ids)
    if not marked_ids:
        return 0
    published_ids = publish_google_calendar_job_batches(marked_ids)
    published_set = set(published_ids)
    unpublished_ids = [
        job_id for job_id in marked_ids if job_id not in published_set
    ]
    if unpublished_ids:
        revert_google_calendar_jobs_to_pending(unpublished_ids)
    if not published_ids:
        return 0
    return sum(1 for _ in chunk_job_ids(published_ids))


def dispatch_if_claimable(message) -> None:
    if message is None:
        return
    if message.status not in DISPATCHABLE_STATUSES:
        return
    if message.attempt_count >= MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS:
        return
    dispatch_google_calendar_job_ids([message.pk])


def reclaim_stale_google_sending_messages():
    now = timezone.localtime()
    stale_before = now - timedelta(minutes=STALE_GOOGLE_CALENDAR_SENDING_MINUTES)
    exhausted = GoogleCalendarOutbox.objects.filter(
        status=GoogleCalendarOutboxStatus.SENDING,
        updated_at__lt=stale_before,
        attempt_count__gte=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
    ).update(
        status=GoogleCalendarOutboxStatus.SKIPPED,
        skip_reason=(
            f"Exceeded max send attempts ({MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS})"
        ),
        error_code="stale_sending",
        error_detail="Send timed out or worker crashed after claim",
        updated_at=now,
    )
    retryable = GoogleCalendarOutbox.objects.filter(
        status=GoogleCalendarOutboxStatus.SENDING,
        updated_at__lt=stale_before,
        attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
    ).update(
        status=GoogleCalendarOutboxStatus.FAILED,
        skip_reason="",
        error_code="stale_sending",
        error_detail="Send timed out or worker crashed after claim; retrying",
        updated_at=now,
    )
    return exhausted + retryable


def reclaim_stale_google_queued_messages():
    now = timezone.localtime()
    stale_before = now - timedelta(minutes=STALE_GOOGLE_CALENDAR_QUEUED_MINUTES)
    return GoogleCalendarOutbox.objects.filter(
        status=GoogleCalendarOutboxStatus.QUEUED,
        updated_at__lt=stale_before,
    ).update(
        status=GoogleCalendarOutboxStatus.PENDING,
        skip_reason="",
        updated_at=now,
    )


def reclaim_stale_google_calendar_messages():
    return reclaim_stale_google_sending_messages() + reclaim_stale_google_queued_messages()


def mark_google_calendar_exhausted(message):
    message.status = GoogleCalendarOutboxStatus.SKIPPED
    message.skip_reason = (
        f"Exceeded max send attempts ({MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS})"
    )
    message.save(update_fields=["status", "skip_reason", "updated_at"])
    return message


def mark_google_calendar_skipped(message, skip_reason):
    message.status = GoogleCalendarOutboxStatus.SKIPPED
    message.skip_reason = skip_reason
    message.save(update_fields=["status", "skip_reason", "updated_at"])
    return message


def mark_google_calendar_accepted(message, *, provider_response=None):
    now = timezone.localtime()
    message.status = GoogleCalendarOutboxStatus.ACCEPTED
    message.accepted_at = now
    message.error_code = ""
    message.error_detail = ""
    message.skip_reason = ""
    update_fields = [
        "status",
        "accepted_at",
        "error_code",
        "error_detail",
        "skip_reason",
        "updated_at",
    ]
    if provider_response is not None:
        message.provider_response = provider_response
        update_fields.append("provider_response")
    message.save(update_fields=update_fields)
    return message


def mark_google_calendar_failed(
    message, *, error_code, error_detail, provider_response=None
):
    now = timezone.localtime()
    message.status = GoogleCalendarOutboxStatus.FAILED
    message.failed_at = now
    message.error_code = str(error_code or "")
    message.error_detail = str(error_detail or "")
    update_fields = [
        "status",
        "failed_at",
        "error_code",
        "error_detail",
        "updated_at",
    ]
    if provider_response is not None:
        message.provider_response = provider_response
        update_fields.append("provider_response")
    message.save(update_fields=update_fields)
    logger.warning(
        f"Google Calendar outbox {message.pk} failed: "
        f"{message.error_code} {message.error_detail}"
    )
    return message


def claim_google_calendar_message(message_id):
    now = timezone.localtime()
    updated = GoogleCalendarOutbox.objects.filter(
        pk=message_id,
        status__in=CLAIMABLE_STATUSES,
        attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
    ).update(
        status=GoogleCalendarOutboxStatus.SENDING,
        attempt_count=F("attempt_count") + 1,
        updated_at=now,
    )
    if updated != 1:
        return None
    return GoogleCalendarOutbox.objects.filter(pk=message_id).first()


def has_in_flight_google_sync_for_message(message):
    target = google_outbox_target_filter_for_message(message)
    if target is None:
        return False
    return GoogleCalendarOutbox.objects.filter(
        status=GoogleCalendarOutboxStatus.SENDING,
        **target,
    ).exists()


def defer_google_calendar_message_for_in_flight(message):
    """
    Sibling sync in flight — leave this row claimable for a later dispatch.
    QUEUED must become PENDING because the SQS receipt is deleted after the
    worker batch exits.
    """
    if message.status != GoogleCalendarOutboxStatus.QUEUED:
        return message
    now = timezone.localtime()
    GoogleCalendarOutbox.objects.filter(
        pk=message.pk,
        status=GoogleCalendarOutboxStatus.QUEUED,
    ).update(
        status=GoogleCalendarOutboxStatus.PENDING,
        skip_reason="",
        updated_at=now,
    )
    return GoogleCalendarOutbox.objects.filter(pk=message.pk).first()


def remaining_google_outbox_job_ids_for_message(message) -> list[UUID]:
    target = google_outbox_target_filter_for_message(message)
    if target is None:
        return []
    return list(
        GoogleCalendarOutbox.objects.filter(
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
            **target,
        )
        .exclude(pk=message.pk)
        .order_by("created_at")
        .values_list("pk", flat=True)
    )


def finish_google_outbox_message(message, result):
    remaining_ids = remaining_google_outbox_job_ids_for_message(message)
    if remaining_ids:
        dispatch_google_calendar_job_ids(remaining_ids)
    return result


def run_google_outbox_desired_state(message):
    if message.appointment_id is not None:
        if not is_google_calendar_configured():
            return "Google Calendar is not configured"
        return sync_appointment_with_google(message.appointment_id)
    if message.availability_series_id is not None:
        return sync_associate_blocks_to_personal_google(
            series_id=message.availability_series_id
        )
    if message.associate_availability_block_id is not None:
        return sync_associate_blocks_to_personal_google(
            block_id=message.associate_availability_block_id
        )
    if message.associate_leave_id is not None:
        return sync_associate_leave_to_personal_google(message.associate_leave_id)
    return "Google Calendar outbox row has no sync target"


def process_google_outbox_message(message):
    try:
        skip_reason = run_google_outbox_desired_state(message)
    except GOOGLE_SYNC_ERRORS as error:
        return finish_google_outbox_message(
            message,
            mark_google_calendar_failed(
                message,
                error_code=type(error).__name__,
                error_detail=describe_google_error(error),
            ),
        )
    if not skip_reason:
        return finish_google_outbox_message(
            message, mark_google_calendar_accepted(message)
        )
    retry_code = RETRYABLE_GOOGLE_SKIP_REASONS.get(skip_reason)
    if retry_code:
        return finish_google_outbox_message(
            message,
            mark_google_calendar_failed(
                message,
                error_code=retry_code,
                error_detail=skip_reason,
            ),
        )
    return finish_google_outbox_message(
        message, mark_google_calendar_skipped(message, skip_reason)
    )


def process_google_calendar_message_by_id(message_id):
    message = GoogleCalendarOutbox.objects.filter(pk=message_id).first()
    if message is None:
        return None
    if message.status == GoogleCalendarOutboxStatus.FAILED and (
        message.attempt_count >= MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS
    ):
        return mark_google_calendar_exhausted(message)
    if message.status not in CLAIMABLE_STATUSES:
        return message
    if has_in_flight_google_sync_for_message(message):
        return defer_google_calendar_message_for_in_flight(message)

    claimed = claim_google_calendar_message(message_id)
    if claimed is None:
        return GoogleCalendarOutbox.objects.filter(pk=message_id).first()
    return process_google_outbox_message(claimed)


def eligible_google_calendar_job_ids(*, limit: int = 50) -> list[UUID]:
    return list(
        GoogleCalendarOutbox.objects.filter(
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_GOOGLE_CALENDAR_OUTBOX_ATTEMPTS,
        )
        .order_by("created_at")
        .values_list("pk", flat=True)[:limit]
    )


def process_google_calendar_job_ids(
    job_ids: list[UUID],
    *,
    queue_url: str = "",
    receipt_handle: str = "",
):
    reclaim_stale_google_calendar_messages()
    results = []
    for job_id in job_ids:
        results.append(process_google_calendar_message_by_id(job_id))
    if receipt_handle and queue_url:
        delete_google_calendar_queue_message(
            queue_url=queue_url,
            receipt_handle=receipt_handle,
        )
    return results


def process_pending_google_calendar_outbox(*, limit: int = 50):
    job_ids = eligible_google_calendar_job_ids(limit=limit)
    return process_google_calendar_job_ids(job_ids)


def dispatch_eligible_google_calendar_jobs(*, limit: int = 50) -> int:
    reclaim_stale_google_calendar_messages()
    job_ids = eligible_google_calendar_job_ids(limit=limit)
    return dispatch_google_calendar_job_ids(job_ids)
