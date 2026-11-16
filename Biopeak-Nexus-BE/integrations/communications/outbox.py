from integrations.communications.whatsapp.outbox import (
    enqueue_appointment_care_message,
    enqueue_whatsapp_message,
    enqueue_whatsapp_only_message,
    process_whatsapp_webhook_payload,
)
from integrations.google_calendar.outbox import (
    enqueue_associate_block_sync,
    enqueue_associate_leave_sync,
    enqueue_google_calendar_message,
    process_google_outbox_message,
)


def enqueue_appointment_message(
    appointment,
    event_type,
    *,
    previous_start_datetime=None,
):
    """
    Persist Google Calendar on GoogleCalendarOutbox and WhatsApp on
    WhatsAppOutbox. Each channel dispatches its own SQS job batches.
    """
    google_message = enqueue_google_calendar_message(appointment, event_type)
    whatsapp_message = enqueue_whatsapp_only_message(
        appointment,
        event_type,
        previous_start_datetime=previous_start_datetime,
        wake=True,
    )
    return whatsapp_message, google_message


__all__ = [
    "enqueue_appointment_care_message",
    "enqueue_appointment_message",
    "enqueue_associate_block_sync",
    "enqueue_associate_leave_sync",
    "enqueue_google_calendar_message",
    "enqueue_whatsapp_message",
    "enqueue_whatsapp_only_message",
    "process_google_outbox_message",
    "process_whatsapp_webhook_payload",
]
