from datetime import timedelta
from uuid import UUID

from django.db import IntegrityError
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, When
from django.utils import timezone

from appointments.models import Appointment
from appointments.utils.constants import AppointmentStatus
from core.utils.log import logger
from integrations.communications.whatsapp.dispatch import (
    delete_whatsapp_queue_message,
    publish_whatsapp_job_batches,
    whatsapp_outbox_queue_url,
)
from integrations.communications.whatsapp.sdk import (
    extract_wamid,
    is_whatsapp_configured,
    send_template,
)
from integrations.communications.whatsapp.templates import (
    build_template_parameters,
    care_template_for_service,
    care_template_name,
    template_language,
    template_name_for_event,
)
from integrations.models import CommunicationWebhookEvent, WhatsAppOutbox
from integrations.utils.constants import (
    CARE_WHATSAPP_EVENT_TYPES,
    CommunicationEventType,
    MAX_WHATSAPP_OUTBOX_ATTEMPTS,
    STALE_WHATSAPP_QUEUED_MINUTES,
    STALE_WHATSAPP_SENDING_MINUTES,
    TERMINAL_APPOINTMENT_EVENT_TYPES,
    TERMINAL_WHATSAPP_OUTBOX_BLOCKING_STATUSES,
    WHATSAPP_DISPATCH_BATCH_SIZE,
    WHATSAPP_EVENT_PROCESS_PRIORITY,
    WhatsAppOutboxStatus,
)
from integrations.utils.sqs_dispatch import chunk_job_ids

STATUS_RANK = {
    WhatsAppOutboxStatus.PENDING: 0,
    WhatsAppOutboxStatus.QUEUED: 1,
    WhatsAppOutboxStatus.SENDING: 2,
    WhatsAppOutboxStatus.ACCEPTED: 3,
    WhatsAppOutboxStatus.SENT: 4,
    WhatsAppOutboxStatus.DELIVERED: 5,
    WhatsAppOutboxStatus.READ: 6,
    WhatsAppOutboxStatus.FAILED: 7,
    WhatsAppOutboxStatus.SKIPPED: 0,
}

WEBHOOK_STATUS_MAP = {
    "sent": WhatsAppOutboxStatus.SENT,
    "delivered": WhatsAppOutboxStatus.DELIVERED,
    "read": WhatsAppOutboxStatus.READ,
    "failed": WhatsAppOutboxStatus.FAILED,
}

ONCE_PER_APPOINTMENT_WHATSAPP_EVENTS = frozenset(
    {
        CommunicationEventType.APPOINTMENT_REMINDER,
        CommunicationEventType.APPOINTMENT_NO_SHOW,
        CommunicationEventType.APPOINTMENT_PRE_CARE,
        CommunicationEventType.APPOINTMENT_POST_CARE,
    }
)

PRE_CARE_SKIP_APPOINTMENT_STATUSES = frozenset(
    {
        AppointmentStatus.CANCELLED,
        AppointmentStatus.NO_SHOW,
        AppointmentStatus.COMPLETED,
        AppointmentStatus.IN_PROGRESS,
    }
)

CONFIRMED_WHATSAPP_SETTLED_STATUSES = frozenset(
    {
        WhatsAppOutboxStatus.ACCEPTED,
        WhatsAppOutboxStatus.SENT,
        WhatsAppOutboxStatus.DELIVERED,
        WhatsAppOutboxStatus.READ,
    }
)

CONFIRMED_WHATSAPP_OPEN_STATUSES = frozenset(
    {
        WhatsAppOutboxStatus.PENDING,
        WhatsAppOutboxStatus.QUEUED,
        WhatsAppOutboxStatus.SENDING,
        WhatsAppOutboxStatus.FAILED,
    }
)

# Worker may claim these.
CLAIMABLE_STATUSES = (
    WhatsAppOutboxStatus.PENDING,
    WhatsAppOutboxStatus.QUEUED,
    WhatsAppOutboxStatus.FAILED,
)

# Only undispatched rows are newly marked QUEUED before SQS publish.
DISPATCHABLE_STATUSES = (
    WhatsAppOutboxStatus.PENDING,
    WhatsAppOutboxStatus.FAILED,
)


def phone_to_whatsapp_recipient(phone):
    if not phone:
        return ""
    digits = "".join(character for character in str(phone) if character.isdigit())
    return digits


def resolve_recipient_phone(appointment):
    profile = appointment.customer_profile
    customer = getattr(profile, "customer", None)
    user = getattr(customer, "user", None)
    return phone_to_whatsapp_recipient(getattr(user, "phone", None))


def existing_terminal_whatsapp(appointment, event_type):
    return (
        WhatsAppOutbox.objects.filter(
            appointment=appointment,
            event_type=event_type,
            status__in=TERMINAL_WHATSAPP_OUTBOX_BLOCKING_STATUSES,
        )
        .order_by("-created_at")
        .first()
    )


def existing_whatsapp_any_status(appointment, event_type):
    return (
        WhatsAppOutbox.objects.filter(
            appointment=appointment,
            event_type=event_type,
        )
        .order_by("-created_at")
        .first()
    )


def create_whatsapp_outbox_message(
    appointment,
    *,
    event_type,
    to_phone="",
    template_name="",
    language="",
    parameters=None,
    status,
    skip_reason="",
):
    try:
        return WhatsAppOutbox.objects.create(
            appointment=appointment,
            event_type=event_type,
            to_phone=to_phone,
            template_name=template_name or "",
            template_language=language,
            template_parameters=parameters or [],
            status=status,
            skip_reason=skip_reason,
        )
    except IntegrityError:
        existing = existing_terminal_whatsapp(appointment, event_type)
        if existing is not None:
            return existing
        if event_type in ONCE_PER_APPOINTMENT_WHATSAPP_EVENTS:
            existing_any = existing_whatsapp_any_status(appointment, event_type)
            if existing_any is not None:
                return existing_any
        raise


def enqueue_whatsapp_message(
    appointment,
    event_type,
    *,
    previous_start_datetime=None,
    template_name=None,
    parameters=None,
):
    to_phone = resolve_recipient_phone(appointment)
    if template_name is None:
        template_name = template_name_for_event(event_type)
    language = template_language()
    if parameters is None:
        parameters = build_template_parameters(
            event_type,
            appointment,
            previous_start_datetime=previous_start_datetime,
        )

    if event_type in ONCE_PER_APPOINTMENT_WHATSAPP_EVENTS:
        existing_any = existing_whatsapp_any_status(appointment, event_type)
        if existing_any is not None:
            return existing_any

    if not is_whatsapp_configured():
        return create_whatsapp_outbox_message(
            appointment,
            event_type=event_type,
            to_phone=to_phone,
            template_name=template_name,
            language=language,
            parameters=parameters,
            status=WhatsAppOutboxStatus.SKIPPED,
            skip_reason="WhatsApp is not configured",
        )

    if not to_phone:
        return create_whatsapp_outbox_message(
            appointment,
            event_type=event_type,
            to_phone="",
            template_name=template_name,
            language=language,
            parameters=parameters,
            status=WhatsAppOutboxStatus.SKIPPED,
            skip_reason="Customer phone is missing",
        )

    if event_type in TERMINAL_APPOINTMENT_EVENT_TYPES:
        existing = existing_terminal_whatsapp(appointment, event_type)
        if existing is not None:
            return existing

    return create_whatsapp_outbox_message(
        appointment,
        event_type=event_type,
        to_phone=to_phone,
        template_name=template_name,
        language=language,
        parameters=parameters,
        status=WhatsAppOutboxStatus.PENDING,
    )


def mark_whatsapp_jobs_queued(job_ids: list[UUID]) -> list[UUID]:
    """
    Conditionally mark PENDING/FAILED rows as QUEUED before SQS publish.
    Returns only ids that this caller successfully marked (overlap-safe).
    """
    now = timezone.localtime()
    marked = []
    for job_id in job_ids:
        updated = WhatsAppOutbox.objects.filter(
            pk=job_id,
            status__in=DISPATCHABLE_STATUSES,
            attempt_count__lt=MAX_WHATSAPP_OUTBOX_ATTEMPTS,
        ).update(
            status=WhatsAppOutboxStatus.QUEUED,
            updated_at=now,
        )
        if updated == 1:
            marked.append(job_id)
    return marked


def revert_whatsapp_jobs_to_pending(job_ids: list[UUID]) -> int:
    """Undo QUEUED when SQS publish missed those ids (local drain can retry)."""
    if not job_ids:
        return 0
    now = timezone.localtime()
    return WhatsAppOutbox.objects.filter(
        pk__in=job_ids,
        status=WhatsAppOutboxStatus.QUEUED,
    ).update(
        status=WhatsAppOutboxStatus.PENDING,
        updated_at=now,
    )


def dispatch_whatsapp_job_ids(job_ids: list[UUID]) -> int:
    """
    Mark claimable rows QUEUED then publish. No queue URL → leave PENDING
    (local `process_whatsapp_outbox --limit`). Publish miss → revert those
    ids to PENDING. Returns number of SQS batches accepted.
    """
    if not whatsapp_outbox_queue_url():
        return 0
    marked_ids = mark_whatsapp_jobs_queued(job_ids)
    if not marked_ids:
        return 0
    published_ids = publish_whatsapp_job_batches(marked_ids)
    published_set = set(published_ids)
    unpublished_ids = [
        job_id for job_id in marked_ids if job_id not in published_set
    ]
    if unpublished_ids:
        revert_whatsapp_jobs_to_pending(unpublished_ids)
    if not published_ids:
        return 0
    return sum(1 for _ in chunk_job_ids(published_ids))


def dispatch_if_claimable(message) -> None:
    if message is None:
        return
    if message.status not in DISPATCHABLE_STATUSES:
        return
    if message.attempt_count >= MAX_WHATSAPP_OUTBOX_ATTEMPTS:
        return
    dispatch_whatsapp_job_ids([message.pk])


def enqueue_whatsapp_only_message(
    appointment,
    event_type,
    *,
    previous_start_datetime=None,
    wake=True,
    template_name=None,
    parameters=None,
):
    """
    Persist WhatsApp outbox only. wake=True publishes SQS job batches when
    the row is claimable. Reminder schedule may pass wake=False then dispatch
    itself after bulk enqueue.
    """
    whatsapp_message = enqueue_whatsapp_message(
        appointment,
        event_type,
        previous_start_datetime=previous_start_datetime,
        template_name=template_name,
        parameters=parameters,
    )
    if wake:
        dispatch_if_claimable(whatsapp_message)
    return whatsapp_message


def enqueue_appointment_care_message(appointment, event_type, *, wake=True):
    if event_type not in CARE_WHATSAPP_EVENT_TYPES:
        return None
    care = care_template_for_service(appointment.service)
    template_name = care_template_name(care, event_type)
    if not template_name:
        return None
    return enqueue_whatsapp_only_message(
        appointment,
        event_type,
        wake=wake,
        template_name=template_name,
        parameters=build_template_parameters(event_type, appointment),
    )


def confirmed_whatsapp_for_appointment(appointment_id):
    return (
        WhatsAppOutbox.objects.filter(
            appointment_id=appointment_id,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
        )
        .order_by("-created_at")
        .first()
    )


def appointment_has_pending_pre_care(appointment_id):
    return WhatsAppOutbox.objects.filter(
        appointment_id=appointment_id,
        event_type=CommunicationEventType.APPOINTMENT_PRE_CARE,
        status__in=CLAIMABLE_STATUSES,
        attempt_count__lt=MAX_WHATSAPP_OUTBOX_ATTEMPTS,
    ).exists()


def maybe_enqueue_pre_care_after_confirmed(message):
    if message.event_type != CommunicationEventType.APPOINTMENT_CONFIRMED:
        return
    if message.appointment_id is None:
        return
    if message.status == WhatsAppOutboxStatus.SKIPPED:
        if appointment_has_pending_pre_care(message.appointment_id):
            dispatch_whatsapp_job_ids(
                list(
                    WhatsAppOutbox.objects.filter(
                        appointment_id=message.appointment_id,
                        event_type=CommunicationEventType.APPOINTMENT_PRE_CARE,
                        status__in=DISPATCHABLE_STATUSES,
                        attempt_count__lt=MAX_WHATSAPP_OUTBOX_ATTEMPTS,
                    ).values_list("pk", flat=True)[:WHATSAPP_DISPATCH_BATCH_SIZE]
                )
            )
        return
    if message.status != WhatsAppOutboxStatus.ACCEPTED:
        return
    appointment = (
        Appointment.objects.select_related(
            "customer_profile__customer__user",
            "service",
            "center",
        )
        .filter(pk=message.appointment_id)
        .first()
    )
    if appointment is None:
        return
    enqueue_appointment_care_message(
        appointment,
        CommunicationEventType.APPOINTMENT_PRE_CARE,
        wake=True,
    )


def pre_care_send_decision(message):
    if message.event_type != CommunicationEventType.APPOINTMENT_PRE_CARE:
        return None, None
    if message.appointment_id is None:
        return "skip", "Appointment is missing"
    appointment_row = (
        Appointment.objects.filter(pk=message.appointment_id)
        .values("status")
        .first()
    )
    if appointment_row is None:
        return "skip", "Appointment is missing"
    if appointment_row["status"] in PRE_CARE_SKIP_APPOINTMENT_STATUSES:
        return "skip", f"Appointment is {appointment_row['status']}"
    confirmed = confirmed_whatsapp_for_appointment(message.appointment_id)
    if confirmed is None:
        return "skip", "Confirmed WhatsApp message is missing"
    if confirmed.status == WhatsAppOutboxStatus.SKIPPED:
        return "skip", "Confirmed WhatsApp was skipped"
    if confirmed.status in CONFIRMED_WHATSAPP_OPEN_STATUSES:
        return "defer", None
    if confirmed.status in CONFIRMED_WHATSAPP_SETTLED_STATUSES:
        return "send", None
    return "skip", f"Confirmed WhatsApp status is {confirmed.status}"


def mark_whatsapp_exhausted(message):
    message.status = WhatsAppOutboxStatus.SKIPPED
    message.skip_reason = (
        f"Exceeded max send attempts ({MAX_WHATSAPP_OUTBOX_ATTEMPTS})"
    )
    message.save(update_fields=["status", "skip_reason", "updated_at"])
    maybe_enqueue_pre_care_after_confirmed(message)
    return message


def mark_whatsapp_skipped(message, skip_reason):
    message.status = WhatsAppOutboxStatus.SKIPPED
    message.skip_reason = skip_reason
    message.save(update_fields=["status", "skip_reason", "updated_at"])
    maybe_enqueue_pre_care_after_confirmed(message)
    return message


def mark_whatsapp_accepted(message, *, wamid="", provider_response=None):
    now = timezone.localtime()
    message.wamid = wamid or message.wamid
    message.status = WhatsAppOutboxStatus.ACCEPTED
    message.accepted_at = now
    message.error_code = ""
    message.error_detail = ""
    message.skip_reason = ""
    update_fields = [
        "wamid",
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
    maybe_enqueue_pre_care_after_confirmed(message)
    return message


def mark_whatsapp_failed(message, *, error_code, error_detail, provider_response=None):
    now = timezone.localtime()
    message.status = WhatsAppOutboxStatus.FAILED
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
        f"WhatsApp outbox {message.pk} failed: {message.error_code} {message.error_detail}"
    )
    maybe_enqueue_pre_care_after_confirmed(message)
    return message


def claim_whatsapp_message(message_id):
    now = timezone.localtime()
    updated = WhatsAppOutbox.objects.filter(
        pk=message_id,
        status__in=CLAIMABLE_STATUSES,
        attempt_count__lt=MAX_WHATSAPP_OUTBOX_ATTEMPTS,
    ).update(
        status=WhatsAppOutboxStatus.SENDING,
        attempt_count=F("attempt_count") + 1,
        updated_at=now,
    )
    if updated != 1:
        return None
    return WhatsAppOutbox.objects.filter(pk=message_id).first()


def reclaim_stale_whatsapp_sending_messages():
    now = timezone.localtime()
    stale_before = now - timedelta(minutes=STALE_WHATSAPP_SENDING_MINUTES)
    return WhatsAppOutbox.objects.filter(
        status=WhatsAppOutboxStatus.SENDING,
        updated_at__lt=stale_before,
    ).update(
        status=WhatsAppOutboxStatus.SKIPPED,
        skip_reason="stale_sending",
        updated_at=now,
    )


def reclaim_stale_whatsapp_queued_messages():
    """
    QUEUED rows with no successful worker claim (lost SQS / failed launch).
    Reset to PENDING so cron/dispatch can republish.
    """
    now = timezone.localtime()
    stale_before = now - timedelta(minutes=STALE_WHATSAPP_QUEUED_MINUTES)
    return WhatsAppOutbox.objects.filter(
        status=WhatsAppOutboxStatus.QUEUED,
        updated_at__lt=stale_before,
    ).update(
        status=WhatsAppOutboxStatus.PENDING,
        skip_reason="",
        updated_at=now,
    )


def reclaim_stale_whatsapp_messages():
    return reclaim_stale_whatsapp_sending_messages() + reclaim_stale_whatsapp_queued_messages()


def refresh_whatsapp_template_parameters(message):
    if message.appointment_id is None:
        return message.template_parameters or []
    appointment = (
        Appointment.objects.filter(pk=message.appointment_id)
        .select_related("center", "service", "customer_profile")
        .first()
    )
    if appointment is None:
        return message.template_parameters or []
    parameters = build_template_parameters(message.event_type, appointment)
    if parameters != (message.template_parameters or []):
        message.template_parameters = parameters
        message.save(update_fields=["template_parameters", "updated_at"])
    return parameters


def process_whatsapp_outbox_message(message):
    if not is_whatsapp_configured():
        return mark_whatsapp_skipped(message, "WhatsApp is not configured")
    if not message.to_phone:
        return mark_whatsapp_skipped(message, "Customer phone is missing")

    body_parameters = refresh_whatsapp_template_parameters(message)
    status_code, body = send_template(
        to_phone=message.to_phone,
        template_name=message.template_name,
        language_code=message.template_language,
        body_parameters=body_parameters,
    )
    if status_code < 300:
        return mark_whatsapp_accepted(
            message,
            wamid=extract_wamid(body) or "",
            provider_response=body,
        )

    error = {}
    if isinstance(body, dict):
        error = (body.get("error") or {}) if isinstance(body.get("error"), dict) else {}
    return mark_whatsapp_failed(
        message,
        error_code=error.get("code") or status_code,
        error_detail=error.get("message") or body,
        provider_response=body,
    )


def confirmed_whatsapp_still_open(appointment_id_field=OuterRef("appointment_id")):
    return WhatsAppOutbox.objects.filter(
        appointment_id=appointment_id_field,
        event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
        status__in=CONFIRMED_WHATSAPP_OPEN_STATUSES,
    )


def event_priority_annotation():
    whens = [
        When(event_type=event_type, then=priority)
        for event_type, priority in WHATSAPP_EVENT_PROCESS_PRIORITY.items()
    ]
    return Case(*whens, default=0, output_field=IntegerField())


def pending_whatsapp_queryset():
    return (
        WhatsAppOutbox.objects.filter(status=WhatsAppOutboxStatus.PENDING)
        .exclude(
            Q(event_type=CommunicationEventType.APPOINTMENT_PRE_CARE)
            & Exists(confirmed_whatsapp_still_open())
        )
        .annotate(process_priority=event_priority_annotation())
        .order_by("process_priority", "created_at")
    )


def failed_whatsapp_queryset():
    return (
        WhatsAppOutbox.objects.filter(
            status=WhatsAppOutboxStatus.FAILED,
            wamid="",
            attempt_count__lt=MAX_WHATSAPP_OUTBOX_ATTEMPTS,
        )
        .exclude(
            Q(event_type=CommunicationEventType.APPOINTMENT_PRE_CARE)
            & Exists(confirmed_whatsapp_still_open())
        )
        .annotate(process_priority=event_priority_annotation())
        .order_by("process_priority", "created_at")
    )


def eligible_whatsapp_job_ids(*, limit: int = 50) -> list[UUID]:
    pending_ids = list(pending_whatsapp_queryset().values_list("pk", flat=True)[:limit])
    remaining = max(limit - len(pending_ids), 0)
    failed_ids = []
    if remaining:
        failed_ids = list(
            failed_whatsapp_queryset().values_list("pk", flat=True)[:remaining]
        )
    seen = set()
    ordered = []
    for job_id in pending_ids + failed_ids:
        if job_id in seen:
            continue
        seen.add(job_id)
        ordered.append(job_id)
    return ordered


def defer_whatsapp_message_for_pre_care(message):
    """
    Confirmed WhatsApp still open — leave pre-care claimable for later.
    QUEUED must become PENDING because the SQS receipt is deleted after the
    worker batch exits.
    """
    if message.status != WhatsAppOutboxStatus.QUEUED:
        return message
    now = timezone.localtime()
    WhatsAppOutbox.objects.filter(
        pk=message.pk,
        status=WhatsAppOutboxStatus.QUEUED,
    ).update(
        status=WhatsAppOutboxStatus.PENDING,
        skip_reason="",
        updated_at=now,
    )
    return WhatsAppOutbox.objects.filter(pk=message.pk).first()


def process_whatsapp_message_by_id(message_id):
    message = WhatsAppOutbox.objects.filter(pk=message_id).first()
    if message is None:
        return None
    if message.status == WhatsAppOutboxStatus.FAILED and (
        message.attempt_count >= MAX_WHATSAPP_OUTBOX_ATTEMPTS
    ):
        return mark_whatsapp_exhausted(message)
    if message.status not in CLAIMABLE_STATUSES:
        return message
    pre_care_action, pre_care_reason = pre_care_send_decision(message)
    if pre_care_action == "skip":
        return mark_whatsapp_skipped(message, pre_care_reason)
    if pre_care_action == "defer":
        return defer_whatsapp_message_for_pre_care(message)

    claimed = claim_whatsapp_message(message_id)
    if claimed is None:
        return WhatsAppOutbox.objects.filter(pk=message_id).first()
    return process_whatsapp_outbox_message(claimed)


def process_whatsapp_job_ids(
    job_ids: list[UUID],
    *,
    queue_url: str = "",
    receipt_handle: str = "",
):
    reclaim_stale_whatsapp_messages()
    results = []
    for job_id in job_ids:
        results.append(process_whatsapp_message_by_id(job_id))
    # Best-effort: ESM may already have deleted after Lambda RunTask success.
    if receipt_handle and queue_url:
        delete_whatsapp_queue_message(
            queue_url=queue_url,
            receipt_handle=receipt_handle,
        )
    return results


def process_pending_whatsapp_outbox(*, limit: int = 50):
    job_ids = eligible_whatsapp_job_ids(limit=limit)
    return process_whatsapp_job_ids(job_ids)


def dispatch_eligible_whatsapp_jobs(*, limit: int = 50) -> int:
    """Mark claimable rows QUEUED and publish non-empty SQS batches (stuck-safe)."""
    reclaim_stale_whatsapp_messages()
    job_ids = eligible_whatsapp_job_ids(limit=limit)
    return dispatch_whatsapp_job_ids(job_ids)


def apply_whatsapp_status_update(status_payload):
    wamid = status_payload.get("id") or ""
    provider_status = status_payload.get("status") or ""
    timestamp = str(status_payload.get("timestamp") or "")
    if not wamid or not provider_status:
        return None

    event_key = f"{wamid}:{provider_status}:{timestamp}"
    try:
        _event, created = CommunicationWebhookEvent.objects.get_or_create(
            event_key=event_key,
            defaults={
                "wamid": wamid,
                "status": provider_status,
                "payload": status_payload,
            },
        )
    except IntegrityError:
        return None
    if not created:
        return None

    message = WhatsAppOutbox.objects.filter(wamid=wamid).first()
    if message is None:
        return None

    mapped_status = WEBHOOK_STATUS_MAP.get(provider_status)
    if mapped_status is None:
        return message

    now = timezone.localtime()
    update_fields = ["updated_at"]

    if mapped_status == WhatsAppOutboxStatus.FAILED:
        errors = status_payload.get("errors") or []
        error = errors[0] if errors else {}
        message.status = WhatsAppOutboxStatus.FAILED
        message.failed_at = now
        message.error_code = str(error.get("code") or "")
        message.error_detail = str(
            (error.get("error_data") or {}).get("details")
            or error.get("message")
            or error.get("title")
            or ""
        )
        update_fields.extend(
            ["status", "failed_at", "error_code", "error_detail"]
        )
        message.save(update_fields=update_fields)
        return message

    current_rank = STATUS_RANK.get(message.status, 0)
    next_rank = STATUS_RANK.get(mapped_status, 0)
    if next_rank > current_rank:
        message.status = mapped_status
        update_fields.append("status")

    if mapped_status == WhatsAppOutboxStatus.SENT and message.sent_at is None:
        message.sent_at = now
        update_fields.append("sent_at")

    if mapped_status in (
        WhatsAppOutboxStatus.DELIVERED,
        WhatsAppOutboxStatus.READ,
    ) and message.delivered_at is None:
        message.delivered_at = now
        update_fields.append("delivered_at")

    if mapped_status == WhatsAppOutboxStatus.READ and message.read_at is None:
        message.read_at = now
        update_fields.append("read_at")

    message.save(update_fields=update_fields)
    return message


def process_whatsapp_webhook_payload(body):
    if not isinstance(body, dict):
        return
    if body.get("object") != "whatsapp_business_account":
        return
    for entry in body.get("entry") or []:
        for change in entry.get("changes") or []:
            if change.get("field") != "messages":
                continue
            value = change.get("value") or {}
            for status_payload in value.get("statuses") or []:
                apply_whatsapp_status_update(status_payload)
