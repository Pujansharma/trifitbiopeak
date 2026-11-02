from decimal import Decimal

from django.db import transaction
from django.db.models import F, Prefetch
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import serializers

from accounts.centers.models import Center
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
from core.utils.log import logger
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from programs.models import (
    Program,
    ProgramAuditLog,
    ProgramPaymentHistory,
    ProgramService,
    RedemptionHistory,
)
from programs.services.serializers import BaseServiceSerializer
from programs.therapy.eligibility import therapy_services_at_center
from programs.utils.audit import create_program_audit_log
from programs.utils.constants import ProgramType


class ProgramAvailableRedeemableCenterSerializer(BaseModelSerializer):
    exists = serializers.BooleanField(read_only=True)
    is_home_center = serializers.BooleanField(read_only=True)

    class Meta:
        model = Center
        fields = ["id", "code", "name", "exists", "is_home_center"]
        read_only_fields = ["id", "code", "name"]


class TherapyServiceAvailableRedeemableCenterSerializer(ProgramAvailableRedeemableCenterSerializer):
    can_redeem = serializers.BooleanField(read_only=True)

    class Meta:
        model = Center
        fields = ["id", "code", "name", "exists", "is_home_center", "can_redeem"]
        read_only_fields = ["id", "code", "name"]


class AssignedProgramServiceSerializer(BaseModelSerializer):
    id = serializers.UUIDField(source="service.pk", read_only=True)
    name = serializers.CharField(source="service.name", read_only=True)
    service_category = serializers.SerializerMethodField()
    service_category_code = serializers.CharField(source="service.service_category", read_only=True)
    image = serializers.FileField(source="service.image", read_only=True)
    centers = serializers.SerializerMethodField()

    class Meta:
        model = ProgramService
        fields = ["id", "name", "service_category", "service_category_code", "image", "centers"]

    @classmethod
    def get_service_category(cls, instance: ProgramService) -> str:
        return instance.service.get_service_category_display()

    def get_centers(self, instance: ProgramService) -> list | None:
        if instance.program.program_type != ProgramType.THERAPY:
            return BaseServiceSerializer(instance.service, context=self.context).data["centers"]
        if not hasattr(instance, "therapy_service"):
            return []
        centers = instance.therapy_service.redeemable_centers.all()
        preview_limit = self.context.get("therapy_center_preview_limit", 3)
        if preview_limit is not None:
            centers = centers[:preview_limit]
        return MinimumCenterSerializer(centers, many=True, context=self.context).data


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
            "is_credit",
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


class ProgramAuditLogSerializer(BaseModelSerializer):
    changed_field_code = serializers.CharField(source="changed_field", read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ProgramAuditLog
        fields = [
            "id", "changed_field", "changed_field_code",
            "previous_value", "current_value", "created_by", "created_at",
        ]
        read_only_fields = [
            "id", "changed_field", "previous_value", "current_value", "created_at",
        ]


class ProgramPaymentHistorySerializer(BaseModelSerializer):
    created_by = BaseUserSerializer(read_only=True)
    is_credit = serializers.BooleanField(required=False, write_only=True)
    is_complimentary = serializers.BooleanField(required=False, write_only=True)

    class Meta:
        model = ProgramPaymentHistory
        fields = [
            "id", "amount_received", "notes", "is_credit", "is_complimentary",
            "created_by", "created_at",
        ]
        read_only_fields = ["id", "created_by", "created_at"]

    def create(self, validated_data: dict):
        program = validated_data["program"]
        program_flags = {}
        for field in ("is_credit", "is_complimentary"):
            if field in validated_data:
                program_flags[field] = validated_data.pop(field)
        if program_flags:
            is_credit = program_flags.get("is_credit", program.is_credit)
            is_complimentary = program_flags.get(
                "is_complimentary", program.is_complimentary,
            )
            if is_complimentary and is_credit:
                raise serializers.ValidationError(
                    {"is_credit": "A program cannot be both complimentary and credit."}
                )
            if not is_complimentary and program.price is None:
                raise serializers.ValidationError(
                    {"price": "Price is required when program is not complimentary."}
                )
        with transaction.atomic():
            Program.objects.filter(pk=program.pk).update(
                credit_received=Coalesce(F("credit_received"), Decimal("0.00"))
                + validated_data["amount_received"],
                updated_at=timezone.localtime(),
                **program_flags,
            )
            payment = super().create(validated_data)
            for field, value in program_flags.items():
                create_program_audit_log(
                    program, field, getattr(program, field), value,
                    validated_data["created_by"],
                )
        logger.info(
            f"ProgramPaymentHistorySerializer.create: program={program.pk} "
            f"payment={payment.pk} amount_received={payment.amount_received} recorded."
        )
        return payment


class TherapyProgramRepresentationSerializer(BaseProgramSerializer):
    credit_received = serializers.DecimalField(
        max_digits=10, decimal_places=2, read_only=True, allow_null=True,
    )

    class Meta(BaseProgramSerializer.Meta):
        fields = [*BaseProgramSerializer.Meta.fields, "credit_received"]


class BaseProgramServiceSerializer(BaseModelSerializer):
    program = serializers.SerializerMethodField()
    service = AssignedProgramServiceSerializer(source="*", read_only=True)
    cancelled_by = BaseUserSerializer(read_only=True)
    can_redeem = serializers.SerializerMethodField()
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

    def get_program(self, instance: ProgramService) -> dict:
        serializer_class = {
            ProgramType.THERAPY: TherapyProgramRepresentationSerializer,
        }.get(instance.program.program_type, BaseProgramSerializer)
        return serializer_class(instance.program, context=self.context).data

    def get_can_redeem(self, instance: ProgramService) -> bool:
        if hasattr(instance, "can_redeem"):
            return instance.can_redeem
        program = instance.program
        if program.program_type != ProgramType.THERAPY:
            return True
        if not hasattr(instance, "therapy_service"):
            return False
        therapy_service = instance.therapy_service
        if not instance.is_active or not therapy_service.is_active or not program.is_active:
            return False
        if not program.therapy_program.is_active:
            return False
        if program.expires_at is not None and program.expires_at < timezone.localdate():
            return False
        if therapy_service.sessions_used >= therapy_service.sessions_count:
            return False
        request = self.context.get("request")
        center_identifier = request.headers.get("X-Center-ID") if request else None
        if center_identifier:
            return therapy_services_at_center(center_identifier).filter(pk=therapy_service.pk).exists()
        return therapy_service.redeemable_centers.filter(
            redeemable_programs=program,
            service_assignments__service=instance.service,
            service_assignments__is_active=True,
        ).exists()

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
