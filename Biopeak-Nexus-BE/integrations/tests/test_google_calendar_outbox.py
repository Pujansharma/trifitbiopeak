from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase, override_settings

from accounts.associates.models import Associate, AssociateRole
from accounts.users.models import User
from appointments.models import AppointmentAssociate, AppointmentHistory
from appointments.utils.constants import AppointmentStatus
from appointments.utils.emails import (
    build_appointment_confirmed_notes,
    build_appointment_rescheduled_notes,
)
from core.utils.constants import AppointmentModes
from integrations.google_calendar.google_sync import (
    google_calendar_event_id,
    sync_appointment_with_google,
)
from integrations.tests.test_whatsapp_outbox import create_appointment
from inventory.models import Room

CUSTOMER_EMAIL = "outbox-customer@example.com"
DOCTOR_EMAIL = "outbox-doctor@example.com"
COACH_EMAIL = "outbox-coach@example.com"


def assign_associate(appointment, email, role_name):
    user = User.objects.create_user(email=email)
    associate = Associate.objects.create(user=user)
    role = AssociateRole.objects.create(
        center=appointment.center, name=role_name, is_active=True
    )
    AppointmentAssociate.objects.create(
        appointment=appointment,
        associate=associate,
        role=role,
        exclusive_start_datetime=appointment.exclusive_start_datetime,
        exclusive_end_datetime=appointment.exclusive_end_datetime,
        appointment_status=appointment.status,
    )
    return associate


def add_reschedule_history(appointment):
    previous_start = appointment.start_datetime - timedelta(days=1)
    previous_end = appointment.end_datetime - timedelta(days=1)
    AppointmentHistory.objects.create(
        appointment=appointment,
        previous_start_datetime=previous_start,
        previous_end_datetime=previous_end,
        previous_exclusive_start_datetime=previous_start,
        previous_exclusive_end_datetime=previous_end,
    )


def make_in_person(appointment):
    center = appointment.center
    center.address_line_1 = "12 MG Road"
    center.city = "Bangalore"
    center.state = "Karnataka"
    center.pincode = "560001"
    center.save()
    appointment.room = Room.objects.create(
        center=center, name="Consultation Room 1", code="RM-OBX-0001"
    )
    appointment.modality = AppointmentModes.IN_PERSON
    appointment.save(update_fields=["room", "modality", "updated_at"])


class GoogleEventIdTests(TestCase):
    def test_deterministic_event_id_is_appointment_hex(self):
        appointment = create_appointment()
        self.assertEqual(google_calendar_event_id(appointment), appointment.pk.hex)


@override_settings(GOOGLE_CALENDAR_ID="care@biopeak.health")
@patch("integrations.google_calendar.google_sync.get_valid_access_token")
@patch("integrations.google_calendar.google_sync.get_fixed_calendar_organizer")
class GoogleDesiredStateTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()
        self.doctor = assign_associate(self.appointment, DOCTOR_EMAIL, "Doctor")

    def use_organizer(self, mock_organizer, mock_token, organizer_pk):
        mock_organizer.return_value.pk = organizer_pk
        mock_token.return_value = "access-token"

    @patch("integrations.google_calendar.google_sync.calendar_api.insert_event")
    def test_confirmed_appointment_inserts_with_deterministic_id(
        self, mock_insert, mock_organizer, mock_token
    ):
        self.use_organizer(mock_organizer, mock_token, self.appointment.pk)
        mock_insert.return_value = {
            "id": self.appointment.pk.hex,
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
        }
        skip_reason = sync_appointment_with_google(self.appointment.pk)
        self.assertIsNone(skip_reason)
        mock_insert.assert_called_once()
        self.assertEqual(
            mock_insert.call_args.kwargs["event_id"],
            self.appointment.pk.hex,
        )
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.google_event_id, self.appointment.pk.hex)
        self.assertEqual(
            self.appointment.google_meet_link,
            "https://meet.google.com/abc-defg-hij",
        )

    @patch("integrations.google_calendar.google_sync.calendar_api.insert_event")
    def test_book_invites_associates_only(
        self, mock_insert, mock_organizer, mock_token
    ):
        assign_associate(self.appointment, COACH_EMAIL, "Health Coach")
        self.use_organizer(mock_organizer, mock_token, self.appointment.pk)
        mock_insert.return_value = {"id": self.appointment.pk.hex}
        sync_appointment_with_google(self.appointment.pk)
        kwargs = mock_insert.call_args.kwargs
        self.assertCountEqual(kwargs["participant_emails"], [DOCTOR_EMAIL, COACH_EMAIL])
        self.assertNotIn(CUSTOMER_EMAIL, kwargs["participant_emails"])
        self.assertEqual(kwargs["title"], "Appointment Confirmed")
        self.assertIn("A new appointment has been booked.", kwargs["notes"])

    @patch("integrations.google_calendar.google_sync.calendar_api.patch_event")
    def test_reschedule_invites_associates_only(
        self, mock_patch, mock_organizer, mock_token
    ):
        self.appointment.google_event_id = self.appointment.pk.hex
        self.appointment.save(update_fields=["google_event_id", "updated_at"])
        add_reschedule_history(self.appointment)
        self.use_organizer(mock_organizer, mock_token, self.appointment.pk)
        mock_patch.return_value = {"id": self.appointment.pk.hex}
        sync_appointment_with_google(self.appointment.pk)
        kwargs = mock_patch.call_args.kwargs
        self.assertEqual(kwargs["participant_emails"], [DOCTOR_EMAIL])
        self.assertEqual(kwargs["title"], "Appointment Rescheduled")
        self.assertIn("This appointment has been rescheduled.", kwargs["notes"])

    @patch("integrations.google_calendar.google_sync.calendar_api.delete_event")
    def test_cancelled_appointment_deletes_event_and_notifies_associates_only(
        self, mock_delete, mock_organizer, mock_token
    ):
        self.appointment.status = AppointmentStatus.CANCELLED
        self.appointment.google_event_id = self.appointment.pk.hex
        self.appointment.save(
            update_fields=["status", "google_event_id", "updated_at"]
        )
        self.use_organizer(mock_organizer, mock_token, self.appointment.pk)
        skip_reason = sync_appointment_with_google(self.appointment.pk)
        self.assertIsNone(skip_reason)
        mock_delete.assert_called_once()
        self.assertEqual(
            mock_delete.call_args.kwargs["participant_emails"], [DOCTOR_EMAIL]
        )
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.google_event_id, self.appointment.pk.hex)

    @patch("integrations.google_calendar.google_sync.calendar_api.insert_event")
    def test_organizer_is_not_invited_to_own_event(
        self, mock_insert, mock_organizer, mock_token
    ):
        assign_associate(self.appointment, COACH_EMAIL, "Health Coach")
        self.use_organizer(mock_organizer, mock_token, self.doctor.pk)
        mock_insert.return_value = {"id": self.appointment.pk.hex}
        sync_appointment_with_google(self.appointment.pk)
        self.assertEqual(
            mock_insert.call_args.kwargs["participant_emails"], [COACH_EMAIL]
        )


class AppointmentInviteNotesTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    def test_in_person_notes_show_room_and_center_address(self):
        make_in_person(self.appointment)
        notes = build_appointment_confirmed_notes(self.appointment, "Bring reports")
        self.assertEqual(
            notes,
            "<b>A new appointment has been booked.</b>\n\n"
            "<b>Customer:</b> Out Box\n"
            "<b>Service:</b> Outbox Service QA\n"
            "<b>Room:</b> Consultation Room 1\n"
            "<b>Center:</b> Outbox Center\n"
            "<b>Center Address:</b> Outbox Center, 12 MG Road, Bangalore, "
            "Karnataka 560001\n"
            "<b>Notes:</b> Bring reports",
        )

    def test_virtual_notes_show_meeting_line_instead_of_address(self):
        notes = build_appointment_confirmed_notes(self.appointment, "Bring reports")
        self.assertEqual(
            notes,
            "<b>A new appointment has been booked.</b>\n\n"
            "<b>Customer:</b> Out Box\n"
            "<b>Service:</b> Outbox Service QA\n"
            "<b>Center:</b> Outbox Center\n"
            "<b>Meeting:</b> Join using the Google Meet link on this invite.\n"
            "<b>Notes:</b> Bring reports",
        )

    def test_rescheduled_notes_only_change_the_headline(self):
        make_in_person(self.appointment)
        confirmed = build_appointment_confirmed_notes(self.appointment, "Bring reports")
        rescheduled = build_appointment_rescheduled_notes(
            self.appointment, "Bring reports"
        )
        self.assertEqual(
            rescheduled,
            confirmed.replace(
                "A new appointment has been booked.",
                "This appointment has been rescheduled.",
            ),
        )

    def test_rows_without_value_are_left_out(self):
        notes = build_appointment_confirmed_notes(self.appointment, None)
        self.assertNotIn("Room:", notes)
        self.assertNotIn("Notes:", notes)

    def test_values_are_html_escaped(self):
        notes = build_appointment_confirmed_notes(self.appointment, "<b>x</b> & y")
        self.assertIn("<b>Notes:</b> &lt;b&gt;x&lt;/b&gt; &amp; y", notes)

    def test_removed_fields_are_not_shown(self):
        make_in_person(self.appointment)
        add_reschedule_history(self.appointment)
        notes = build_appointment_rescheduled_notes(self.appointment, "Bring reports")
        for label in (
            "Hi ",
            "Appointment ID:",
            "Date:",
            "Time:",
            "Previous Date & Time:",
            "Mode:",
            "Equipment:",
            "Care Team:",
            "Assigned Associates:",
            "RM-OBX-0001",
        ):
            self.assertNotIn(label, notes)
