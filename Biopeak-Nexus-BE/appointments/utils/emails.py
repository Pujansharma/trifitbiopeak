import html

from appointments.models import Appointment
from core.utils.constants import AppointmentModes

VIRTUAL_MEETING_NOTE = "Join using the Google Meet link on this invite."
CONFIRMED_HEADLINE = "A new appointment has been booked."
RESCHEDULED_HEADLINE = "This appointment has been rescheduled."


def build_location_row(appointment: Appointment) -> tuple[str, str]:
    if appointment.modality == AppointmentModes.VIRTUAL:
        return "Meeting", VIRTUAL_MEETING_NOTE
    return "Center Address", appointment.center.full_address


def get_room_label(appointment: Appointment) -> str | None:
    room = appointment.room
    if room is None:
        return None
    return room.name


def build_detail_rows(
    appointment: Appointment, notes: str | None
) -> list[tuple[str, str | None]]:
    location_label, location_value = build_location_row(appointment)
    return [
        ("Customer", appointment.customer_profile.get_full_name()),
        ("Service", appointment.service.name),
        ("Room", get_room_label(appointment)),
        ("Center", appointment.center.name),
        (location_label, location_value),
        ("Notes", notes),
    ]


def render_notes(headline: str, rows: list[tuple[str, str | None]]) -> str:
    # Rows without a value (no room, no notes, ...) are left out of the invite.
    details = "\n".join(
        f"<b>{label}:</b> {html.escape(value)}" for label, value in rows if value
    )
    return f"<b>{headline}</b>\n\n{details}"


def build_appointment_confirmed_notes(appointment: Appointment, notes: str | None) -> str:
    return render_notes(CONFIRMED_HEADLINE, build_detail_rows(appointment, notes))


def build_appointment_rescheduled_notes(appointment: Appointment, notes: str | None) -> str:
    return render_notes(RESCHEDULED_HEADLINE, build_detail_rows(appointment, notes))
