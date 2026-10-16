from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.utils import timezone

from accounts.centers.models import Center
from accounts.customers.models import Customer, CustomerProfile
from accounts.users.models import User
from appointments.models import Appointment
from appointments.utils.constants import AppointmentStatus
from core.utils.constants import AppointmentModes
from integrations.communications.outbox import (
    MAX_OUTBOX_ATTEMPTS,
    STALE_SENDING_MINUTES,
    apply_whatsapp_status_update,
    enqueue_appointment_care_message,
    enqueue_appointment_message,
    enqueue_whatsapp_only_message,
    mark_outbox_accepted,
    pending_outbox_queryset,
    process_outbox_message,
    reclaim_stale_sending_messages,
)
from integrations.communications.service import (
    enqueue_due_appointment_reminders,
    queue_confirmed_by_appointment_id,
    schedule_queue_appointment_post_care,
    send_appointment_confirmed,
    send_appointment_pre_care,
)
from integrations.communications.whatsapp.templates import (
    VIRTUAL_MEET_LINK_FALLBACK,
    build_template_parameters,
    template_name_for_event,
)
from integrations.models import CommunicationOutbox, CommunicationWebhookEvent
from integrations.utils.constants import (
    CommunicationChannel,
    CommunicationEventType,
    CommunicationOutboxStatus,
    WHATSAPP_TEMPLATE_BY_EVENT,
)
from programs.services.models import Service, ServiceCareTemplate
from programs.services.utils.constants import ServiceCategory

UTC = ZoneInfo("UTC")


def create_appointment():
    center = Center.objects.create(name="Outbox Center", code="CT-OBX")
    user = User.objects.create_user(
        email="outbox-customer@example.com",
        phone="+91-9876543210",
    )
    customer = Customer.objects.create(user=user, contact_email=user.email)
    profile = CustomerProfile.objects.create(
        customer=customer,
        first_name="Out",
        last_name="Box",
        is_main=True,
    )
    service = Service.objects.create(
        name="Outbox Service QA",
        service_category=ServiceCategory.CONSULTATION,
    )
    start = datetime(2026, 9, 15, 9, 0, tzinfo=UTC)
    end = start + timedelta(minutes=30)
    appointment = Appointment.objects.create(
        center=center,
        code="APT-OBX-001",
        customer_profile=profile,
        service=service,
        modality=AppointmentModes.VIRTUAL,
        start_datetime=start,
        end_datetime=end,
        duration_minutes=30,
        exclusive_start_datetime=start,
        exclusive_end_datetime=end,
        status=AppointmentStatus.CONFIRMED,
    )
    return appointment


class WhatsAppOutboxReclaimTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_stale_sending_reclaimed_as_skipped_not_failed(self, mock_wake):
        stale_at = timezone.now() - timedelta(minutes=STALE_SENDING_MINUTES + 1)
        message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        CommunicationOutbox.objects.filter(pk=message.pk).update(updated_at=stale_at)
        updated = reclaim_stale_sending_messages()
        self.assertEqual(updated, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, CommunicationOutboxStatus.SKIPPED)
        self.assertEqual(message.error_code, "stale_sending")
        self.assertIn("not retried", message.skip_reason)
        mock_wake.assert_called_once()

    def test_fresh_sending_not_reclaimed(self):
        message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CANCELLED,
            to_phone="919876543210",
            template_name="appointment_cancelled_template",
            template_language="en",
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        updated = reclaim_stale_sending_messages()
        self.assertEqual(updated, 0)
        message.refresh_from_db()
        self.assertEqual(message.status, CommunicationOutboxStatus.SENDING)


class WhatsAppWebhookIdempotencyTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()
        self.message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.ACCEPTED,
            wamid="wamid.test.1",
        )

    def test_duplicate_webhook_event_is_noop(self):
        payload = {
            "id": "wamid.test.1",
            "status": "delivered",
            "timestamp": "1710000000",
        }
        first = apply_whatsapp_status_update(payload)
        self.assertIsNotNone(first)
        second = apply_whatsapp_status_update(payload)
        self.assertIsNone(second)
        self.assertEqual(
            CommunicationWebhookEvent.objects.filter(
                event_key="wamid.test.1:delivered:1710000000"
            ).count(),
            1,
        )
        self.message.refresh_from_db()
        self.assertEqual(self.message.status, CommunicationOutboxStatus.DELIVERED)


class CommunicationOutboxEnqueueTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        GOOGLE_CALENDAR_ID="care@biopeak.health",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_enqueue_creates_whatsapp_and_google_pending_rows(self, mock_wake):
        whatsapp_message, google_message = enqueue_appointment_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_CONFIRMED,
        )
        self.assertEqual(whatsapp_message.channel, CommunicationChannel.WHATSAPP)
        self.assertEqual(whatsapp_message.status, CommunicationOutboxStatus.PENDING)
        self.assertEqual(
            google_message.channel, CommunicationChannel.GOOGLE_CALENDAR
        )
        self.assertEqual(google_message.status, CommunicationOutboxStatus.PENDING)
        self.assertLessEqual(google_message.created_at, whatsapp_message.created_at)
        mock_wake.assert_called_once()
        self.assertEqual(
            CommunicationOutbox.objects.filter(appointment=self.appointment).count(),
            2,
        )

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        GOOGLE_CALENDAR_ID="care@biopeak.health",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_google_coalesces_open_row_for_same_appointment(self, mock_wake):
        first_whatsapp, first_google = enqueue_appointment_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_CONFIRMED,
        )
        second_whatsapp, second_google = enqueue_appointment_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_RESCHEDULED,
        )
        self.assertEqual(first_google.pk, second_google.pk)
        self.assertNotEqual(first_whatsapp.pk, second_whatsapp.pk)
        self.assertEqual(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                channel=CommunicationChannel.GOOGLE_CALENDAR,
            ).count(),
            1,
        )
        self.assertEqual(mock_wake.call_count, 2)


class WhatsAppReminderNoShowEnqueueTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    def test_template_names_come_from_constants(self):
        self.assertEqual(
            template_name_for_event(CommunicationEventType.APPOINTMENT_CONFIRMED),
            WHATSAPP_TEMPLATE_BY_EVENT[CommunicationEventType.APPOINTMENT_CONFIRMED],
        )
        self.assertEqual(
            template_name_for_event(CommunicationEventType.APPOINTMENT_REMINDER),
            "therapy_session_reminder",
        )
        self.assertEqual(
            template_name_for_event(CommunicationEventType.APPOINTMENT_NO_SHOW),
            "therapy_session_no_show",
        )

    def test_reminder_params_are_positional(self):
        self.appointment.google_meet_link = "https://meet.google.com/abc-defg-hij"
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_REMINDER,
            self.appointment,
        )
        self.assertEqual(len(parameters), 4)
        self.assertIsInstance(parameters[0], str)
        self.assertEqual(parameters[0], "Out Box")
        self.assertEqual(parameters[2], "Outbox Service QA")
        self.assertEqual(parameters[3], "https://meet.google.com/abc-defg-hij")

    def test_virtual_without_meet_link_uses_fallback(self):
        self.appointment.google_meet_link = None
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_REMINDER,
            self.appointment,
        )
        self.assertEqual(parameters[3], VIRTUAL_MEET_LINK_FALLBACK)

    def test_no_show_in_person_uses_clinic_address(self):
        self.appointment.modality = AppointmentModes.IN_PERSON
        self.appointment.center.address_line_1 = "12 Main St"
        self.appointment.center.city = "Mumbai"
        self.appointment.center.save(
            update_fields=["address_line_1", "city", "updated_at"]
        )
        self.appointment.save(update_fields=["modality", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_NO_SHOW,
            self.appointment,
        )
        self.assertIn("Outbox Center", parameters[3])
        self.assertIn("12 Main St", parameters[3])

    def test_confirmed_virtual_clinic_address_is_meet_link(self):
        self.appointment.google_meet_link = "https://meet.google.com/abc-defg-hij"
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_CONFIRMED,
            self.appointment,
        )
        clinic_address = next(
            item["text"]
            for item in parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(clinic_address, "https://meet.google.com/abc-defg-hij")

    def test_confirmed_virtual_without_meet_uses_fallback(self):
        self.appointment.google_meet_link = None
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_CONFIRMED,
            self.appointment,
        )
        clinic_address = next(
            item["text"]
            for item in parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(clinic_address, VIRTUAL_MEET_LINK_FALLBACK)

    def test_confirmed_in_person_clinic_address_is_center(self):
        self.appointment.modality = AppointmentModes.IN_PERSON
        self.appointment.center.address_line_1 = "12 Main St"
        self.appointment.center.city = "Mumbai"
        self.appointment.center.save(
            update_fields=["address_line_1", "city", "updated_at"]
        )
        self.appointment.save(update_fields=["modality", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_CONFIRMED,
            self.appointment,
        )
        clinic_address = next(
            item["text"]
            for item in parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertIn("Outbox Center", clinic_address)
        self.assertIn("12 Main St", clinic_address)

    def test_rescheduled_virtual_clinic_address_is_meet_link(self):
        self.appointment.google_meet_link = "https://meet.google.com/xyz-uvwx-rst"
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        parameters = build_template_parameters(
            CommunicationEventType.APPOINTMENT_RESCHEDULED,
            self.appointment,
        )
        clinic_address = next(
            item["text"]
            for item in parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(clinic_address, "https://meet.google.com/xyz-uvwx-rst")

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_reminder_enqueue_skips_wake_and_google(self, mock_wake):
        message = enqueue_whatsapp_only_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_REMINDER,
            wake=False,
        )
        self.assertEqual(message.channel, CommunicationChannel.WHATSAPP)
        self.assertEqual(message.event_type, CommunicationEventType.APPOINTMENT_REMINDER)
        self.assertEqual(message.template_name, "therapy_session_reminder")
        self.assertEqual(message.status, CommunicationOutboxStatus.PENDING)
        mock_wake.assert_not_called()
        self.assertEqual(
            CommunicationOutbox.objects.filter(appointment=self.appointment).count(),
            1,
        )
        self.assertFalse(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                channel=CommunicationChannel.GOOGLE_CALENDAR,
            ).exists()
        )

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_no_show_enqueue_wakes_whatsapp_only(self, mock_wake):
        message = enqueue_whatsapp_only_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_NO_SHOW,
            wake=True,
        )
        self.assertEqual(message.event_type, CommunicationEventType.APPOINTMENT_NO_SHOW)
        self.assertEqual(message.template_name, "therapy_session_no_show")
        mock_wake.assert_called_once()
        self.assertFalse(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                channel=CommunicationChannel.GOOGLE_CALENDAR,
            ).exists()
        )

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_due_reminders_enqueue_once(self, mock_wake):
        now = timezone.now()
        self.appointment.start_datetime = now + timedelta(minutes=45)
        self.appointment.end_datetime = self.appointment.start_datetime + timedelta(
            minutes=30
        )
        self.appointment.exclusive_start_datetime = self.appointment.start_datetime
        self.appointment.exclusive_end_datetime = self.appointment.end_datetime
        self.appointment.save(
            update_fields=[
                "start_datetime",
                "end_datetime",
                "exclusive_start_datetime",
                "exclusive_end_datetime",
                "updated_at",
            ]
        )
        first = enqueue_due_appointment_reminders()
        second = enqueue_due_appointment_reminders()
        self.assertEqual(len(first), 1)
        self.assertEqual(second, [])
        self.assertEqual(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                event_type=CommunicationEventType.APPOINTMENT_REMINDER,
            ).count(),
            1,
        )
        mock_wake.assert_not_called()

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_failed_reminder_blocks_sweep_reenqueue(self, mock_wake):
        now = timezone.now()
        self.appointment.start_datetime = now + timedelta(minutes=45)
        self.appointment.end_datetime = self.appointment.start_datetime + timedelta(
            minutes=30
        )
        self.appointment.exclusive_start_datetime = self.appointment.start_datetime
        self.appointment.exclusive_end_datetime = self.appointment.end_datetime
        self.appointment.save(
            update_fields=[
                "start_datetime",
                "end_datetime",
                "exclusive_start_datetime",
                "exclusive_end_datetime",
                "updated_at",
            ]
        )
        first = enqueue_whatsapp_only_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_REMINDER,
            wake=False,
        )
        CommunicationOutbox.objects.filter(pk=first.pk).update(
            status=CommunicationOutboxStatus.FAILED,
            attempt_count=1,
        )
        second_batch = enqueue_due_appointment_reminders()
        self.assertEqual(second_batch, [])
        self.assertEqual(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                event_type=CommunicationEventType.APPOINTMENT_REMINDER,
            ).count(),
            1,
        )
        mock_wake.assert_not_called()

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_skipped_reminder_blocks_sweep_reenqueue(self, mock_wake):
        now = timezone.now()
        self.appointment.start_datetime = now + timedelta(minutes=45)
        self.appointment.end_datetime = self.appointment.start_datetime + timedelta(
            minutes=30
        )
        self.appointment.exclusive_start_datetime = self.appointment.start_datetime
        self.appointment.exclusive_end_datetime = self.appointment.end_datetime
        self.appointment.save(
            update_fields=[
                "start_datetime",
                "end_datetime",
                "exclusive_start_datetime",
                "exclusive_end_datetime",
                "updated_at",
            ]
        )
        first = enqueue_whatsapp_only_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_REMINDER,
            wake=False,
        )
        CommunicationOutbox.objects.filter(pk=first.pk).update(
            status=CommunicationOutboxStatus.SKIPPED,
            skip_reason="Exceeded max send attempts (2)",
            attempt_count=2,
        )
        second_batch = enqueue_due_appointment_reminders()
        self.assertEqual(second_batch, [])
        self.assertEqual(
            CommunicationOutbox.objects.filter(
                appointment=self.appointment,
                event_type=CommunicationEventType.APPOINTMENT_REMINDER,
            ).count(),
            1,
        )
        mock_wake.assert_not_called()


class GoogleOutboxReclaimTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    def test_stale_google_sending_reclaimed_as_failed(self):
        stale_at = timezone.now() - timedelta(minutes=STALE_SENDING_MINUTES + 1)
        message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        CommunicationOutbox.objects.filter(pk=message.pk).update(updated_at=stale_at)
        updated = reclaim_stale_sending_messages()
        self.assertEqual(updated, 1)
        message.refresh_from_db()
        self.assertEqual(message.status, CommunicationOutboxStatus.FAILED)
        self.assertEqual(message.error_code, "stale_sending")
        self.assertIn("retrying", message.error_detail)

    def test_exhausted_stale_google_sending_skipped(self):
        stale_at = timezone.now() - timedelta(minutes=STALE_SENDING_MINUTES + 1)
        message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=MAX_OUTBOX_ATTEMPTS,
        )
        CommunicationOutbox.objects.filter(pk=message.pk).update(updated_at=stale_at)
        reclaim_stale_sending_messages()
        message.refresh_from_db()
        self.assertEqual(message.status, CommunicationOutboxStatus.SKIPPED)


class GoogleOutboxProcessTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()
        self.message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.PENDING,
        )

    @override_settings(GOOGLE_CALENDAR_ID="care@biopeak.health")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value=None,
    )
    def test_google_process_marks_accepted(self, mock_sync):
        processed = process_outbox_message(self.message.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.ACCEPTED)
        mock_sync.assert_called_once_with(self.appointment.pk)

    @override_settings(GOOGLE_CALENDAR_ID="care@biopeak.health")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value="Google Calendar organizer is disconnected",
    )
    def test_google_disconnected_is_retryable_failed(self, mock_sync):
        processed = process_outbox_message(self.message.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.FAILED)
        self.assertEqual(processed.error_code, "organizer_disconnected")
        self.assertEqual(processed.attempt_count, 1)
        mock_sync.assert_called_once()

    @override_settings(GOOGLE_CALENDAR_ID="care@biopeak.health")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        side_effect=ValueError("Failed to persist google_event_id"),
    )
    def test_google_persist_failure_is_retryable_failed(self, mock_sync):
        processed = process_outbox_message(self.message.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.FAILED)
        self.assertEqual(processed.attempt_count, 1)
        mock_sync.assert_called_once()

    def test_google_waits_when_another_row_is_sending(self):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CANCELLED,
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        processed = process_outbox_message(self.message.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.PENDING)
        self.assertEqual(processed.attempt_count, 0)

    @override_settings(GOOGLE_CALENDAR_ID="care@biopeak.health")
    @patch("integrations.communications.outbox.publish_outbox_wake")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value=None,
    )
    def test_google_wakes_remaining_row_for_same_appointment(
        self, mock_sync, mock_wake
    ):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CANCELLED,
            status=CommunicationOutboxStatus.PENDING,
        )
        process_outbox_message(self.message.pk)
        mock_sync.assert_called_once()
        mock_wake.assert_called_once()


class WhatsAppDeferForGoogleMeetTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()

    def test_virtual_whatsapp_defers_while_google_pending(self):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.PENDING,
        )
        whatsapp = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            template_parameters=[],
            status=CommunicationOutboxStatus.PENDING,
        )
        processed = process_outbox_message(whatsapp.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.PENDING)
        self.assertEqual(processed.attempt_count, 0)

    def test_virtual_with_meet_does_not_defer_for_google(self):
        self.appointment.google_meet_link = "https://meet.google.com/abc-defg-hij"
        self.appointment.save(update_fields=["google_meet_link", "updated_at"])
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_RESCHEDULED,
            status=CommunicationOutboxStatus.PENDING,
        )
        whatsapp = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_RESCHEDULED,
            to_phone="919876543210",
            template_name="appointment_rescheduled_template",
            template_language="en",
            template_parameters=[
                {
                    "parameter_name": "clinic_address",
                    "text": VIRTUAL_MEET_LINK_FALLBACK,
                },
            ],
            status=CommunicationOutboxStatus.PENDING,
        )
        with (
            override_settings(
                WHATSAPP_ACCESS_TOKEN="token",
                WHATSAPP_PHONE_NUMBER_ID="123",
            ),
            patch(
                "integrations.communications.outbox.send_template",
                return_value=(200, {"messages": [{"id": "wamid.reschedule"}]}),
            ) as mock_send,
        ):
            processed = process_outbox_message(whatsapp.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.ACCEPTED)
        clinic_address = next(
            item["text"]
            for item in mock_send.call_args.kwargs["body_parameters"]
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(clinic_address, "https://meet.google.com/abc-defg-hij")

    def test_cancel_whatsapp_does_not_defer_for_google(self):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CANCELLED,
            status=CommunicationOutboxStatus.PENDING,
        )
        whatsapp = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CANCELLED,
            to_phone="919876543210",
            template_name="appointment_cancelled_template",
            template_language="en",
            template_parameters=[],
            status=CommunicationOutboxStatus.PENDING,
        )
        with (
            override_settings(
                WHATSAPP_ACCESS_TOKEN="token",
                WHATSAPP_PHONE_NUMBER_ID="123",
            ),
            patch(
                "integrations.communications.outbox.send_template",
                return_value=(200, {"messages": [{"id": "wamid.cancel"}]}),
            ) as mock_send,
        ):
            processed = process_outbox_message(whatsapp.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.ACCEPTED)
        mock_send.assert_called_once()

    def test_in_person_whatsapp_does_not_defer_for_google(self):
        self.appointment.modality = AppointmentModes.IN_PERSON
        self.appointment.save(update_fields=["modality", "updated_at"])
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.PENDING,
        )
        whatsapp = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            template_parameters=[
                {"parameter_name": "clinic_address", "text": "stale"},
            ],
            status=CommunicationOutboxStatus.PENDING,
        )
        with (
            override_settings(
                WHATSAPP_ACCESS_TOKEN="token",
                WHATSAPP_PHONE_NUMBER_ID="123",
            ),
            patch(
                "integrations.communications.outbox.send_template",
                return_value=(200, {"messages": [{"id": "wamid.inperson"}]}),
            ) as mock_send,
        ):
            processed = process_outbox_message(whatsapp.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.ACCEPTED)
        mock_send.assert_called_once()

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        GOOGLE_CALENDAR_ID="care@biopeak.health",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value=None,
    )
    @patch(
        "integrations.communications.outbox.send_template",
        return_value=(200, {"messages": [{"id": "wamid.meet"}]}),
    )
    def test_virtual_whatsapp_rebuilds_meet_after_google(
        self, mock_send, mock_sync, mock_wake
    ):
        def sync_and_set_meet(appointment_id):
            Appointment.objects.filter(pk=appointment_id).update(
                google_meet_link="https://meet.google.com/abc-defg-hij"
            )
            return None

        mock_sync.side_effect = sync_and_set_meet
        google = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.PENDING,
        )
        whatsapp = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            template_parameters=[
                {
                    "parameter_name": "clinic_address",
                    "text": VIRTUAL_MEET_LINK_FALLBACK,
                },
            ],
            status=CommunicationOutboxStatus.PENDING,
        )
        process_outbox_message(google.pk)
        processed = process_outbox_message(whatsapp.pk)
        self.assertEqual(processed.status, CommunicationOutboxStatus.ACCEPTED)
        sent_parameters = mock_send.call_args.kwargs["body_parameters"]
        clinic_address = next(
            item["text"]
            for item in sent_parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(clinic_address, "https://meet.google.com/abc-defg-hij")
        whatsapp.refresh_from_db()
        stored = next(
            item["text"]
            for item in whatsapp.template_parameters
            if item["parameter_name"] == "clinic_address"
        )
        self.assertEqual(stored, "https://meet.google.com/abc-defg-hij")
        mock_wake.assert_called()

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        GOOGLE_CALENDAR_ID="care@biopeak.health",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value=None,
    )
    def test_google_accept_wakes_pending_whatsapp(self, mock_sync, mock_wake):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.PENDING,
        )
        google = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.GOOGLE_CALENDAR,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            status=CommunicationOutboxStatus.PENDING,
        )
        process_outbox_message(google.pk)
        mock_wake.assert_called_once()


class WhatsAppCareMessageTests(TestCase):
    def setUp(self):
        self.appointment = create_appointment()
        ServiceCareTemplate.objects.create(
            service=self.appointment.service,
            pre_template_name="service_pre_care",
            post_template_name="service_post_care",
        )

    def test_care_params_always_empty(self):
        pre_params = build_template_parameters(
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            self.appointment,
        )
        self.assertEqual(pre_params, [])
        post_params = build_template_parameters(
            CommunicationEventType.APPOINTMENT_POST_CARE,
            self.appointment,
        )
        self.assertEqual(post_params, [])

    def test_enqueue_care_uses_service_template_names(self):
        with self.settings(
            WHATSAPP_ACCESS_TOKEN="token",
            WHATSAPP_PHONE_NUMBER_ID="123",
            COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
        ):
            with patch("integrations.communications.outbox.publish_outbox_wake"):
                pre = enqueue_appointment_care_message(
                    self.appointment,
                    CommunicationEventType.APPOINTMENT_PRE_CARE,
                )
                post = enqueue_appointment_care_message(
                    self.appointment,
                    CommunicationEventType.APPOINTMENT_POST_CARE,
                )
        self.assertEqual(pre.template_name, "service_pre_care")
        self.assertEqual(pre.template_parameters, [])
        self.assertEqual(post.template_name, "service_post_care")
        self.assertEqual(post.template_parameters, [])

    def test_blank_pre_template_skips_enqueue(self):
        ServiceCareTemplate.objects.filter(
            service_id=self.appointment.service_id
        ).update(pre_template_name="")
        result = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
        )
        self.assertIsNone(result)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_pre_care_defers_until_confirmed_accepted(self, mock_wake):
        confirmed = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.PENDING,
        )
        pre = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            wake=False,
        )
        process_outbox_message(pre.pk)
        pre.refresh_from_db()
        self.assertEqual(pre.status, CommunicationOutboxStatus.PENDING)

        confirmed.status = CommunicationOutboxStatus.ACCEPTED
        confirmed.save(update_fields=["status", "updated_at"])
        with patch(
            "integrations.communications.outbox.send_template",
            return_value=(200, {"messages": [{"id": "wamid.care"}]}),
        ):
            process_outbox_message(pre.pk)
        pre.refresh_from_db()
        self.assertEqual(pre.status, CommunicationOutboxStatus.ACCEPTED)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_pre_care_skips_when_confirmed_skipped(self, mock_wake):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.SKIPPED,
            skip_reason="WhatsApp is not configured",
        )
        pre = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            wake=False,
        )
        process_outbox_message(pre.pk)
        pre.refresh_from_db()
        self.assertEqual(pre.status, CommunicationOutboxStatus.SKIPPED)
        self.assertIn("skipped", pre.skip_reason.lower())

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_pre_care_skips_when_appointment_cancelled(self, mock_wake):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.ACCEPTED,
        )
        self.appointment.status = AppointmentStatus.CANCELLED
        self.appointment.save(update_fields=["status", "updated_at"])
        pre = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            wake=False,
        )
        process_outbox_message(pre.pk)
        pre.refresh_from_db()
        self.assertEqual(pre.status, CommunicationOutboxStatus.SKIPPED)
        self.assertIn("cancelled", pre.skip_reason)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
        GOOGLE_CALENDAR_ID="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    @patch(
        "integrations.communications.outbox.sync_appointment_with_google",
        return_value=None,
    )
    def test_confirmed_queue_does_not_enqueue_pre_care_yet(
        self, mock_sync, mock_wake
    ):
        queue_confirmed_by_appointment_id(self.appointment.pk)
        pre = CommunicationOutbox.objects.filter(
            appointment=self.appointment,
            event_type=CommunicationEventType.APPOINTMENT_PRE_CARE,
        ).first()
        self.assertIsNone(pre)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_confirmed_accepted_enqueues_pre_care(self, mock_wake):
        confirmed = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        mark_outbox_accepted(confirmed, wamid="wamid.confirmed")
        pre = CommunicationOutbox.objects.filter(
            appointment=self.appointment,
            event_type=CommunicationEventType.APPOINTMENT_PRE_CARE,
        ).first()
        self.assertIsNotNone(pre)
        self.assertEqual(pre.template_name, "service_pre_care")
        self.assertEqual(pre.status, CommunicationOutboxStatus.PENDING)

    def test_pending_drain_excludes_pre_care_while_confirmed_open(self):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.PENDING,
        )
        pre = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            wake=False,
        )
        pending_ids = set(pending_outbox_queryset().values_list("pk", flat=True))
        self.assertNotIn(pre.pk, pending_ids)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_pre_care_skips_when_appointment_completed(self, mock_wake):
        CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_CONFIRMED,
            to_phone="919876543210",
            template_name="appointment_confirmed_template",
            template_language="en",
            status=CommunicationOutboxStatus.ACCEPTED,
        )
        self.appointment.status = AppointmentStatus.COMPLETED
        self.appointment.save(update_fields=["status", "updated_at"])
        pre = enqueue_appointment_care_message(
            self.appointment,
            CommunicationEventType.APPOINTMENT_PRE_CARE,
            wake=False,
        )
        process_outbox_message(pre.pk)
        pre.refresh_from_db()
        self.assertEqual(pre.status, CommunicationOutboxStatus.SKIPPED)
        self.assertIn("completed", pre.skip_reason)

    def test_care_event_requires_explicit_template_name(self):
        with self.assertRaises(ValueError) as raised:
            template_name_for_event(CommunicationEventType.APPOINTMENT_PRE_CARE)
        self.assertIn("explicit template_name", str(raised.exception))

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_schedule_post_care_enqueues_outbox_row(self, mock_wake):
        with self.captureOnCommitCallbacks(execute=True):
            schedule_queue_appointment_post_care(self.appointment)
        post = CommunicationOutbox.objects.filter(
            appointment=self.appointment,
            event_type=CommunicationEventType.APPOINTMENT_POST_CARE,
        ).first()
        self.assertIsNotNone(post)
        self.assertEqual(post.template_name, "service_post_care")
        self.assertEqual(post.status, CommunicationOutboxStatus.PENDING)

    @override_settings(
        WHATSAPP_ACCESS_TOKEN="token",
        WHATSAPP_PHONE_NUMBER_ID="123",
        COMMUNICATION_OUTBOX_WAKE_QUEUE_URL="",
    )
    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_schedule_post_care_skips_when_blank_template(self, mock_wake):
        ServiceCareTemplate.objects.filter(
            service=self.appointment.service
        ).update(post_template_name="")
        with self.captureOnCommitCallbacks(execute=True):
            schedule_queue_appointment_post_care(self.appointment)
        post = CommunicationOutbox.objects.filter(
            appointment=self.appointment,
            event_type=CommunicationEventType.APPOINTMENT_POST_CARE,
        ).first()
        self.assertIsNone(post)

    @patch("integrations.communications.outbox.publish_outbox_wake")
    def test_stale_non_confirmed_reclaim_does_not_wake(self, mock_wake):
        stale_at = timezone.now() - timedelta(minutes=STALE_SENDING_MINUTES + 1)
        message = CommunicationOutbox.objects.create(
            appointment=self.appointment,
            channel=CommunicationChannel.WHATSAPP,
            event_type=CommunicationEventType.APPOINTMENT_REMINDER,
            to_phone="919876543210",
            template_name="therapy_session_reminder",
            template_language="en",
            status=CommunicationOutboxStatus.SENDING,
            attempt_count=1,
        )
        CommunicationOutbox.objects.filter(pk=message.pk).update(updated_at=stale_at)
        reclaim_stale_sending_messages()
        mock_wake.assert_not_called()
