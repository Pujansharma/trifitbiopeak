from django.db.models import Prefetch
from rest_framework import serializers

from accounts.centers.serializers import MinimumCenterSerializer
from accounts.customers.serializers import BaseCustomerProfileSerializer
from accounts.users.serializers import BaseUserSerializer
from appointments.models import AppointmentAssociate
from appointments.serializers.booking import (
    AppointmentAssociateNestedSerializer,
    AppointmentCareTeamNestedSerializer,
    AppointmentEquipmentNestedSerializer,
    AppointmentRoomNestedSerializer,
)
from appointments.utils.redemption import OPEN_APPOINTMENT_STATUSES
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from programs.models import Program, ProgramService, RedemptionHistory
from programs.services.serializers import BaseServiceSerializer


class BaseProgramSerializer(BaseModelSerializer):
    uid = serializers.CharField(read_only=True)
    profile = BaseCustomerProfileSerializer(source="customer_profile", read_only=True)
    sessions_count = serializers.IntegerField(
        source="therapy_program.sessions_count", read_only=True
    )
    sessions_used = serializers.IntegerField(
        source="therapy_program.sessions_used", read_only=True
    )
    sessions_cancelled = serializers.IntegerField(
        source="therapy_program.sessions_cancelled",
        read_only=True,
        allow_null=True,
        default=None,
    )
    created_date = serializers.DateField(read_only=True)
    cancelled_date = serializers.DateField(read_only=True, allow_null=True)

    class Meta:
        model = Program
        fields = [
            "id",
            "uid",
            "profile",
            "program_type",
            "notes",
            "expires_at",
            "is_complimentary",
            "price",
            "services_count",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeemable_centers_count",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "created_date",
            "cancelled_date",
            "is_active",
            "created_at",
            "updated_at",
        ]


class ProgramSerializer(BaseModelSerializer):
    uid = serializers.CharField(read_only=True)

    class Meta:
        model = Program
        fields = ["id", "uid"]


class BaseProgramServiceSerializer(BaseModelSerializer):
    program = BaseProgramSerializer(read_only=True)
    service = BaseServiceSerializer(read_only=True)
    cancelled_by = BaseUserSerializer(read_only=True)
    can_redeem = serializers.BooleanField(default=True, read_only=True)
    sessions_count = serializers.IntegerField(
        source="therapy_service.sessions_count", read_only=True
    )
    sessions_used = serializers.IntegerField(
        source="therapy_service.sessions_used", read_only=True
    )
    sessions_cancelled = serializers.IntegerField(
        source="therapy_service.sessions_cancelled", read_only=True
    )
    redeem_code = serializers.CharField(
        source="therapy_service.redeem_code", read_only=True
    )
    created_date = serializers.DateField(read_only=True)
    cancelled_date = serializers.DateField(read_only=True, allow_null=True)
    active_appointment = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ProgramService
        fields = [
            "id",
            "program",
            "service",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeem_code",
            "created_date",
            "created_at",
            "is_active",
            "can_redeem",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
            "active_appointment",
        ]

    def get_active_appointment(self, obj: ProgramService) -> dict | None:
        open_appointments = getattr(obj, "open_appointments", None)
        if open_appointments is None:
            open_appointments = list(
                obj.appointments.filter(status__in=OPEN_APPOINTMENT_STATUSES)
                .select_related("center", "care_team", "room", "equipment")
                .prefetch_related(
                    Prefetch(
                        "associate_links",
                        queryset=AppointmentAssociate.objects.select_related(
                            "associate__user", "role"
                        ),
                    )
                )[:1]
            )
        if not open_appointments:
            return None
        return ProgramServiceActiveAppointmentSerializer(
            open_appointments[0], context=self.context
        ).data


class RedeemableCenterField(BaseSerializer):
    id = serializers.UUIDField(required=True)


class ServiceField(BaseSerializer):
    id = serializers.UUIDField(required=True)
    sessions_count = serializers.IntegerField(min_value=1, required=True)


class RedemptionHistoryAppointmentSerializer(BaseSerializer):
    id = serializers.UUIDField(source="pk", read_only=True)
    code = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    start = serializers.DateTimeField(source="start_datetime", read_only=True)
    end = serializers.DateTimeField(source="end_datetime", read_only=True)


class ProgramServiceActiveAppointmentSerializer(RedemptionHistoryAppointmentSerializer):
    center = MinimumCenterSerializer(read_only=True)
    associates = AppointmentAssociateNestedSerializer(
        source="associate_links", many=True, read_only=True
    )
    care_team = AppointmentCareTeamNestedSerializer(read_only=True, allow_null=True)
    room = AppointmentRoomNestedSerializer(read_only=True, allow_null=True)
    equipment = AppointmentEquipmentNestedSerializer(read_only=True, allow_null=True)


class ProgramServiceRedemptionHistorySerializer(BaseModelSerializer):
    redeem_center = MinimumCenterSerializer(read_only=True)
    redeemed_by = BaseUserSerializer(read_only=True)
    appointment = RedemptionHistoryAppointmentSerializer(read_only=True, allow_null=True)

    class Meta:
        model = RedemptionHistory
        fields = [
            "id",
            "redemption_type",
            "redeem_center",
            "redeemed_date",
            "redeemed_at",
            "quantity",
            "redeemed_by",
            "appointment",
        ]
        read_only_fields = fields
