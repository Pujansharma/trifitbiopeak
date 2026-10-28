from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from django.http import QueryDict
from django.test import SimpleTestCase, TestCase

from accounts.centers.models import Center
from accounts.utils.constants import UserType
from appointments.models import Appointment
from appointments.serializers.booking import (
    AppointmentCalendarListSerializer,
    created_by_type_for_actor,
)
from appointments.utils.constants import (
    AppointmentCreatedByType,
    AvailabilityGranularity,
)
from appointments.views.booking import (
    apply_appointment_list_filters,
    appointment_list_applies_hard_cap,
    appointment_list_uses_date_window,
    parse_optional_uuid_query,
)


class AppointmentListQueryHelperTests(SimpleTestCase):
    def test_search_without_start_skips_date_window(self):
        params = QueryDict("search=Meera")
        self.assertFalse(appointment_list_uses_date_window(params))

    def test_search_with_start_uses_date_window(self):
        params = QueryDict("search=Meera&start=2026-09-01")
        self.assertTrue(appointment_list_uses_date_window(params))

    def test_no_search_uses_date_window(self):
        params = QueryDict("start=2026-09-01&granularity=week")
        self.assertTrue(appointment_list_uses_date_window(params))

    def test_unscoped_search_applies_hard_cap(self):
        params = QueryDict("search=Meera")
        self.assertTrue(appointment_list_applies_hard_cap(params))

    def test_week_window_applies_hard_cap(self):
        params = QueryDict(f"start=2026-09-01&granularity={AvailabilityGranularity.WEEK}")
        self.assertTrue(appointment_list_applies_hard_cap(params))

    def test_day_window_skips_hard_cap(self):
        params = QueryDict(f"start=2026-09-01&granularity={AvailabilityGranularity.DAY}")
        self.assertFalse(appointment_list_applies_hard_cap(params))

    def test_junk_uuid_rejected(self):
        params = QueryDict("associate_id=not-a-uuid")
        value, error = parse_optional_uuid_query(params, "associate_id")
        self.assertIsNone(value)
        self.assertEqual(error, "Invalid associate_id.")

    def test_blank_uuid_omitted(self):
        params = QueryDict("associate_id=")
        value, error = parse_optional_uuid_query(params, "associate_id")
        self.assertIsNone(value)
        self.assertIsNone(error)


class AppointmentListStaffFilterTests(TestCase):
    def test_associate_and_role_combine_with_or(self):
        associate_id = "11111111-1111-1111-1111-111111111111"
        role_id = "22222222-2222-2222-2222-222222222222"
        params = QueryDict(f"associate_id={associate_id}&role_id={role_id}")
        queryset, error = apply_appointment_list_filters(
            Appointment.objects.all(),
            params,
        )
        self.assertIsNone(error)
        sql = str(queryset.query).upper()
        self.assertIn(" OR ", sql)
        self.assertIn("ASSOCIATE_ID", sql)
        self.assertIn("ROLE_ID", sql)

    def test_invalid_status_rejected(self):
        params = QueryDict("status=pending")
        queryset, error = apply_appointment_list_filters(
            Appointment.objects.all(),
            params,
        )
        self.assertIsNone(queryset)
        self.assertIn("Invalid status", error)


def calendar_list_row(created_by_type):
    model_row = Appointment(created_by_type=created_by_type)
    center = Center(code="C", name="Center")
    row = SimpleNamespace(
        pk=uuid4(),
        code="APT-1",
        start_datetime=datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc),
        end_datetime=datetime(2026, 10, 22, 10, 0, tzinfo=timezone.utc),
        status="confirmed",
        modality="in_person",
        is_late=False,
        late_by=None,
        has_open_exception=False,
        customer_profile=SimpleNamespace(
            pk=uuid4(), first_name="Meera", last_name="Shah"
        ),
        service=SimpleNamespace(pk=uuid4(), name="Consult"),
        program_service_id=None,
        care_team=None,
        associate_links=[],
        room=None,
        equipment=None,
        center=center,
        notes=None,
        google_meet_link=None,
        created_by_type=created_by_type,
    )
    display = getattr(model_row, "get_created_by_type_display", None)
    if display is not None:
        row.get_created_by_type_display = display
    return row


class AppointmentCreatedByTypeTests(SimpleTestCase):
    def test_customer(self):
        actor = SimpleNamespace(
            account=SimpleNamespace(account_type=UserType.CUSTOMER)
        )
        self.assertEqual(created_by_type_for_actor(actor), "customer")

    def test_staff_account_types(self):
        for account_type in (
            UserType.ADMIN,
            UserType.ASSOCIATE,
            UserType.SUPERUSER,
        ):
            actor = SimpleNamespace(
                account=SimpleNamespace(account_type=account_type)
            )
            self.assertEqual(created_by_type_for_actor(actor), "staff")

    def test_missing_actor_is_null(self):
        self.assertIsNone(created_by_type_for_actor(None))

    def test_missing_account_is_null(self):
        self.assertIsNone(created_by_type_for_actor(SimpleNamespace()))

    def test_unknown_account_type_is_null(self):
        actor = SimpleNamespace(
            account=SimpleNamespace(account_type=UserType.UNKNOWN)
        )
        self.assertIsNone(created_by_type_for_actor(actor))

    def test_calendar_list_emits_stored_code(self):
        data = AppointmentCalendarListSerializer(
            calendar_list_row(AppointmentCreatedByType.STAFF)
        ).data
        self.assertEqual(data["created_by_type"], "staff")

    def test_calendar_list_emits_null(self):
        data = AppointmentCalendarListSerializer(calendar_list_row(None)).data
        self.assertIsNone(data["created_by_type"])
