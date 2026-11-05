from collections import Counter
from uuid import UUID

from django.db import transaction
from django.db.models import F, Prefetch, prefetch_related_objects
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from accounts.centers.models import Center
from accounts.centers.serializers import BaseCenterSerializer, MinimumCenterSerializer
from accounts.customers.models import CustomerCenterAssignment, CustomerProfile
from accounts.customers.serializers import CustomerProfileWithCenterSerializer
from accounts.users.models import User
from accounts.users.serializers import BaseUserSerializer
from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from programs.models import (
    Program,
    ProgramService,
    TherapyProgram,
    TherapyProgramService,
)
from programs.serializers import (
    AssignedProgramServiceSerializer,
    BaseProgramServiceSerializer,
    TherapyProgramRepresentationSerializer,
)
from programs.services.models import CenterServiceAssignment, Service
from programs.services.serializers import ServiceSerializer
from programs.services.utils.constants import ServiceCategory
from programs.services.utils.db import (
    redeem_all_program_services,
)
from programs.utils.audit import create_program_audit_log
from programs.utils.constants import ProgramType
from programs.utils.db import (
    cancel_all_program_services,
    discard_therapy_program,
    update_program_redeemable_centers_count,
    update_program_services_count,
    update_program_sessions_count,
)
from programs.utils.helper import generate_program_unique_id


class TherapyProgramAvailableServiceSerializer(ServiceSerializer):
    exists = serializers.BooleanField(read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "is_global",
            "add_centers",
            "remove_centers",
            "centers",
            "service_category",
            "service_category_code",
            "image",
            "centers_count",
            "care_template",
            "created_at",
            "updated_at",
            "is_active",
            "is_locked",
            "created_by",
            "exists",
        ]


class BaseTherapyProgramSerializer(BaseModelSerializer):
    id = serializers.UUIDField(source="pk", read_only=True)

    class Meta:
        model = TherapyProgram
        fields = ["id"]


class TherapyProgramServiceSerializer(BaseModelSerializer):
    is_discarded = serializers.BooleanField(read_only=True)
    discarded_by = BaseUserSerializer(read_only=True)
    id = serializers.UUIDField(source="program_service.id", read_only=True)
    redeemable_centers = MinimumCenterSerializer(many=True, read_only=True)
    program = TherapyProgramRepresentationSerializer(
        source="program_service.program", read_only=True,
    )
    service = AssignedProgramServiceSerializer(source="program_service", read_only=True)
    service_assignment_type = serializers.SerializerMethodField(read_only=True)
    service_assignment_type_code = serializers.CharField(
        source='program_service.assignment_type', read_only=True
    )

    cancelled_by = BaseUserSerializer(
        source="program_service.cancelled_by", read_only=True
    )
    cancellation_reason = serializers.CharField(
        source="program_service.cancellation_reason", read_only=True
    )
    cancelled_at = serializers.DateTimeField(
        source="program_service.cancelled_at", read_only=True
    )
    cancelled_date = serializers.DateField(
        source="program_service.cancelled_date", read_only=True
    )
    created_date = serializers.DateField(
        source="program_service.created_date", read_only=True
    )

    class Meta:
        model = TherapyProgramService
        fields = [
            "id",
            "program",
            "service",
            "service_assignment_type",
            "service_assignment_type_code",
            "redeemable_centers",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeem_code",
            "created_date",
            "created_at",
            "is_active",
            "is_discarded",
            "discarded_by",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
        ]
        read_only_fields = [
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeem_code",
        ]

    @classmethod
    def get_service_assignment_type(
            cls, instance: TherapyProgramService,
    ):
        return instance.program_service.get_assignment_type_display()

    def create(self, validated_data):
        raise serializers.ValidationError("Create not allowed.")

    def update(self, instance: TherapyProgramService, validated_data):
        program_service_data = validated_data.pop("program_service", {})
        program_service = instance.program_service
        for attr, value in program_service_data.items():
            setattr(program_service, attr, value)
        if program_service_data:
            program_service.save(update_fields=list(program_service_data.keys()))
        return super().update(instance, validated_data)


class TherapyCenterAdditionSerializer(BaseSerializer):
    id = serializers.UUIDField()


class TherapyServiceAdditionSerializer(TherapyCenterAdditionSerializer):
    sessions_count = serializers.IntegerField(min_value=1, required=False)
    centers = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )


class TherapyProgramSerializer(BaseModelSerializer):
    is_discarded = serializers.BooleanField(read_only=True)
    discarded_by = BaseUserSerializer(read_only=True)
    id = serializers.UUIDField(source="pk", read_only=True)
    uid = serializers.CharField(source="program.uid", read_only=True)
    profile = CustomerProfileWithCenterSerializer(
        source="program.customer_profile", read_only=True
    )
    profile_id = serializers.UUIDField(write_only=True, required=True)
    # center = BaseCenterSerializer(source='program.center', read_only=True)
    program_type = serializers.ChoiceField(
        source="program.program_type", choices=ProgramType, read_only=True
    )
    notes = serializers.CharField(
        source="program.notes", required=False, allow_null=True, allow_blank=True
    )
    expires_at = serializers.DateField(source="program.expires_at", required=True)
    is_complimentary = serializers.BooleanField(
        source="program.is_complimentary", default=True
    )
    is_credit = serializers.BooleanField(source="program.is_credit", default=False)
    credit_received = serializers.DecimalField(
        source="program.credit_received", max_digits=10, decimal_places=2,
        min_value=0, required=False, allow_null=True,
    )
    price = serializers.DecimalField(
        source="program.price",
        allow_null=True,
        required=False,
        max_digits=10,
        decimal_places=2,
    )
    services_count = serializers.IntegerField(
        source="program.services_count", default=0, read_only=True
    )

    redeemable_centers_count = serializers.IntegerField(
        source="program.redeemable_centers_count", default=0, read_only=True
    )
    redeemable_centers = serializers.SerializerMethodField(read_only=True)
    services = serializers.SerializerMethodField(read_only=True)

    # Many to many write only fields
    add_redeemable_centers = TherapyCenterAdditionSerializer(many=True, write_only=True)
    add_services = TherapyServiceAdditionSerializer(
        many=True, required=True, allow_empty=False, write_only=True
    )

    # Dates
    created_date = serializers.DateField(source="program.created_date", required=False)
    cancelled_date = serializers.DateField(
        source="program.cancelled_date", required=False
    )

    # Read only
    created_by = BaseUserSerializer(source="program.created_by", read_only=True)

    class Meta:
        model = TherapyProgram
        fields = [
            "id",
            "uid",
            "profile",
            "profile_id",
            # "center",
            "program_type",
            "notes",
            "expires_at",
            "is_complimentary",
            "is_credit",
            "credit_received",
            "price",
            "services_count",
            "sessions_count",
            "sessions_cancelled",
            "sessions_used",
            "redeemable_centers",
            "redeemable_centers_count",
            "services",
            "add_redeemable_centers",
            "add_services",
            "created_date",
            "cancelled_date",
            "created_at",
            "updated_at",
            "is_active",
            "is_discarded",
            "discarded_by",
            "created_by",
        ]
        read_only_fields = ["sessions_count", "sessions_used", "sessions_cancelled", "is_active"]

    def get_services(self, instance):
        qs = getattr(instance.program, "service_preview", [])[:5]
        return BaseProgramServiceSerializer(qs, many=True, context=self.context).data

    def get_redeemable_centers(self, instance):
        qs = getattr(instance.program, "redeemable_center_preview", None)
        if qs is None:
            qs = instance.program.redeemable_centers.all()
        return BaseCenterSerializer(qs[:5], many=True, context=self.context).data

    @classmethod
    def get_center(cls, center_identifier: UUID, created_by: User):
        filter_kwargs = {"pk": center_identifier, "is_active": True}
        if get_user_account_type(created_by) == UserType.ASSOCIATE:
            filter_kwargs.update(
                associate_assignments__associate=created_by.associate,
                associate_assignments__is_active=True,
            )
        return Center.objects.filter(**filter_kwargs).distinct().first()

    @classmethod
    def authorize_program_update(cls, program: Program, user: User):
        if get_user_account_type(user) == UserType.ADMIN:
            return
        if get_user_account_type(user) != UserType.ASSOCIATE:
            raise PermissionDenied("Only staff may update therapy programs.")
        center_identifiers = set(
            program.redeemable_centers.values_list("pk", flat=True)
        )
        center_identifiers.add(program.center.pk)
        if not Center.objects.filter(
                pk__in=center_identifiers,
                associate_assignments__associate=user.associate,
                associate_assignments__is_active=True,
        ).exists():
            raise PermissionDenied("You are not assigned to a center of this program.")

    @classmethod
    def validate_program_metadata(
            cls, program_data: dict, program: Program | None
    ):
        expires_at = program_data.get(
            "expires_at", program.expires_at if program else None
        )
        if expires_at is not None and expires_at < timezone.localdate():
            raise serializers.ValidationError(
                {"expires_at": "Expiry date cannot be earlier than today's date."}
            )
        if program and program.expires_at and program.expires_at < timezone.localdate():
            if program_data.get("expires_at") is None:
                raise serializers.ValidationError(
                    {
                        "expires_at": "An expired program must be renewed in this request."
                    }
                )
        is_complimentary = program_data.get(
            "is_complimentary", program.is_complimentary if program else True
        )
        is_credit = program_data.get(
            "is_credit", program.is_credit if program else False
        )
        if is_complimentary and is_credit:
            raise serializers.ValidationError(
                {"is_credit": "A program cannot be both complimentary and credit."}
            )
        if program is None and is_credit and program_data.get("credit_received") is None:
            raise serializers.ValidationError(
                {"credit_received": "Credit amount is required when program is credit."}
            )
        price = program_data.get("price", program.price if program else None)
        if not is_complimentary and price is None:
            raise serializers.ValidationError(
                {"price": "Price is required when program is not complimentary."}
            )

    @classmethod
    def validate_center_additions(
            cls, customer_profile: CustomerProfile, center_identifiers: set[UUID]
    ):
        valid_identifiers = set(
            Center.objects.filter(
                pk__in=center_identifiers,
                customer_assignments__customer_profile=customer_profile,
            ).values_list("pk", flat=True)
        )
        missing_identifiers = center_identifiers - valid_identifiers
        if missing_identifiers:
            raise serializers.ValidationError(
                {
                    "add_redeemable_centers": f"Invalid center IDs provided: {', '.join(sorted(map(str, missing_identifiers)))}."
                }
            )

    @classmethod
    def validate_service_additions(
            cls,
            program: Program | None,
            service_data: list[dict],
            center_identifiers: set[UUID],
    ):
        identifier_counts = Counter(item.get("id") for item in service_data)
        if any(count > 1 for count in identifier_counts.values()):
            raise serializers.ValidationError(
                {"add_services": "Duplicate service IDs are not allowed."}
            )
        services = {
            service.pk: service
            for service in Service.objects.filter(
                pk__in=identifier_counts, service_category=ServiceCategory.THERAPY
            )
        }
        if set(identifier_counts) - services.keys():
            raise serializers.ValidationError(
                {"add_services": "Invalid therapy service IDs provided."}
            )
        existing_services = {}
        if program is not None:
            for program_service in ProgramService.objects.filter(
                    program=program, service__pk__in=identifier_counts
            ).select_related("service", "therapy_service"):
                service_identifier = program_service.service.pk
                if service_identifier in existing_services:
                    raise serializers.ValidationError(
                        {"add_services": "Multiple assignments match a service ID."}
                    )
                existing_services[service_identifier] = program_service
        requested_centers = set().union(
            *(set(item.get("centers", [])) for item in service_data)
        )
        available_pairs = set(
            CenterServiceAssignment.objects.filter(
                service__pk__in=identifier_counts,
                center__pk__in=requested_centers,
                is_active=True,
            ).values_list("service__pk", "center__pk")
        )
        errors = [{} for item in service_data]
        for index, item in enumerate(service_data):
            existing_service = existing_services.get(item["id"])
            selected_centers = set(item.get("centers", []))
            if existing_service is None:
                if "sessions_count" not in item:
                    errors[index]["sessions_count"] = (
                        "This field is required for a new service."
                    )
                if not selected_centers:
                    errors[index]["centers"] = (
                        "Select at least one center for a new service."
                    )
            if existing_service is not None and (
                    not existing_service.is_active
                    or not hasattr(existing_service, "therapy_service")
                    or not existing_service.therapy_service.is_active
                    or existing_service.therapy_service.is_discarded
            ):
                errors[index]["id"] = "This service assignment is cancelled, discarded, or invalid."
            if selected_centers - center_identifiers:
                errors[index]["centers"] = (
                    "Centers must belong to the program's redeemable centers."
                )
            unavailable_centers = {
                center_identifier
                for center_identifier in selected_centers
                if (item["id"], center_identifier) not in available_pairs
            }
            if unavailable_centers:
                errors[index]["centers"] = (
                    "This service is not available at every selected center."
                )
        if any(errors):
            raise serializers.ValidationError({"add_services": errors})
        return services, existing_services

    @classmethod
    def apply_service_additions(
            cls,
            program: Program,
            user: User,
            service_data: list[dict],
            services: dict,
            existing_services: dict,
    ):
        for item in service_data:
            program_service = existing_services.get(item["id"])
            if program_service is None:
                program_service = ProgramService.objects.create(
                    program=program, service=services[item["id"]], created_by=user
                )
                therapy_service = TherapyProgramService.objects.create(
                    program_service=program_service,
                    sessions_count=item["sessions_count"],
                )
            else:
                therapy_service = program_service.therapy_service
                if "sessions_count" in item:
                    TherapyProgramService.objects.filter(pk=therapy_service.pk).update(
                        sessions_count=F("sessions_count") + item["sessions_count"],
                        updated_at=timezone.localtime(),
                    )
            therapy_service.redeemable_centers.add(*set(item.get("centers", [])))

    @classmethod
    def refresh_program(cls, instance: TherapyProgram):
        program = instance.program
        update_program_sessions_count(program.pk)
        update_program_services_count(program.pk)
        update_program_redeemable_centers_count(program.pk)
        TherapyProgram.objects.filter(pk=instance.pk).update(updated_at=timezone.localtime())
        program.refresh_from_db()
        instance.refresh_from_db()
        instance.program = program
        program.therapy_program = instance
        if hasattr(program, "redeemable_center_preview"):
            del program.redeemable_center_preview
        prefetch_related_objects(
            [program],
            Prefetch(
                "redeemable_centers",
                queryset=Center.objects.all(),
                to_attr="redeemable_center_preview",
            ),
            "created_by",
            "customer_profile__customer__user",
            Prefetch(
                "customer_profile__center_assignments",
                queryset=CustomerCenterAssignment.objects.filter(is_primary=True).select_related("center"),
                to_attr="primary_center_assignments",
            ),
        )
        return instance

    def create(self, validated_data: dict):
        customer_profile = validated_data.pop("customer_profile", None)
        if customer_profile is None:
            profile_identifier = validated_data.pop("profile_id")
            customer_profile = CustomerProfile.objects.filter(pk=profile_identifier).first()
            if customer_profile is None:
                raise serializers.ValidationError(
                    {"profile_id": "Invalid profile ID provided."}
                )
        user = validated_data.pop("created_by")
        center_identifier = validated_data.pop("center_id")
        program_data = validated_data.pop("program", {})
        center_identifiers = {
            item.get("id") for item in validated_data.pop("add_redeemable_centers", [])
        }
        service_data = validated_data.pop("add_services")
        self.validate_program_metadata(program_data, None)
        center = self.get_center(center_identifier, user)
        if center is None:
            raise serializers.ValidationError(
                {"center_id": "Invalid or unauthorized center ID provided."}
            )
        self.validate_center_additions(customer_profile, center_identifiers)
        services, existing_services = self.validate_service_additions(
            None, service_data, center_identifiers
        )
        with transaction.atomic():
            program = Program.objects.create(
                **program_data,
                uid=generate_program_unique_id(),
                program_type=ProgramType.THERAPY,
                customer_profile=customer_profile,
                center=center,
                created_by=user,
            )
            program.redeemable_centers.add(*center_identifiers)
            instance = TherapyProgram.objects.create(program=program)
            self.apply_service_additions(
                program, user, service_data, services, existing_services
            )
            return self.refresh_program(instance)

    def update(self, instance: TherapyProgram, validated_data: dict):
        user = self.context["request"].user
        program = instance.program
        self.authorize_program_update(program, user)
        if instance.is_discarded:
            raise serializers.ValidationError("Discarded programs cannot be updated.")
        if not program.is_active or not instance.is_active:
            raise serializers.ValidationError("Cancelled programs cannot be updated.")
        program_data = validated_data.pop("program", {})
        program_data.pop("credit_received", None)
        self.validate_program_metadata(program_data, program)
        center_identifier = validated_data.pop("center_id", None)
        if center_identifier is not None and center_identifier != program.center.pk:
            center = self.get_center(center_identifier, user)
            if center is None:
                raise serializers.ValidationError(
                    {"center_id": "Invalid or unauthorized center ID provided."}
                )
            program_data["center"] = center
        center_identifiers = {
            item.get("id") for item in validated_data.pop("add_redeemable_centers", [])
        }
        self.validate_center_additions(program.customer_profile, center_identifiers)
        service_data = validated_data.pop("add_services", [])
        with transaction.atomic():
            # Save metadata before reading assignments so concurrent additions share the program write transaction.
            for attribute, value in program_data.items():
                create_program_audit_log(
                    program, attribute, getattr(program, attribute), value, user,
                )
                setattr(program, attribute, value)
            program.save(update_fields=[*program_data, "updated_at"])
            if TherapyProgram.objects.filter(pk=instance.pk, is_discarded=True).exists():
                raise serializers.ValidationError("Discarded programs cannot be updated.")
            existing_centers = set(
                program.redeemable_centers.values_list("pk", flat=True)
            )
            all_centers = existing_centers | center_identifiers
            services, existing_services = self.validate_service_additions(
                program, service_data, all_centers
            )
            program.redeemable_centers.add(*center_identifiers)
            create_program_audit_log(
                program,
                "redeemable_centers",
                sorted(map(str, existing_centers)),
                sorted(map(str, all_centers)),
                user,
            )
            self.apply_service_additions(
                program, user, service_data, services, existing_services
            )
            return self.refresh_program(instance)


class TherapyProgramDetailSerializer(TherapyProgramSerializer):
    credit_received = serializers.DecimalField(
        source="program.credit_received",
        max_digits=10,
        decimal_places=2,
        read_only=True,
        allow_null=True,
    )
    center_id = serializers.UUIDField(write_only=True, required=False)
    add_redeemable_centers = TherapyCenterAdditionSerializer(many=True, write_only=True, required=False)
    add_services = TherapyServiceAdditionSerializer(many=True, write_only=True, required=False)
    is_complimentary = serializers.BooleanField(source="program.is_complimentary")
    is_credit = serializers.BooleanField(source="program.is_credit")
    expires_at = serializers.DateField(
        source="program.expires_at", required=False, allow_null=True
    )
    services_count = serializers.IntegerField(
        source="program.services_count", read_only=True
    )
    redeemable_centers_count = serializers.IntegerField(
        source="program.redeemable_centers_count", read_only=True
    )
    cancellation_reason = serializers.CharField(
        source="program.cancellation_reason", read_only=True
    )
    cancelled_by = BaseUserSerializer(source="program.cancelled_by", read_only=True)
    cancelled_at = serializers.DateTimeField(
        source="program.cancelled_at", read_only=True
    )
    cancelled_date = serializers.DateField(source="program.cancelled_date", read_only=True)

    class Meta:
        model = TherapyProgram
        fields = [
            "id",
            "center_id",
            "add_redeemable_centers",
            "add_services",
            "services",
            "uid",
            "profile",
            "program_type",
            "is_complimentary",
            "is_credit",
            "credit_received",
            "price",
            "notes",
            "expires_at",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "services_count",
            "redeemable_centers",
            "redeemable_centers_count",
            "created_by",
            "created_at",
            "updated_at",
            "is_active",
            "is_discarded",
            "discarded_by",
            # Cancellation
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "created_date",
            "cancelled_date",
        ]
        read_only_fields = ["sessions_count", "sessions_used", "sessions_cancelled", "is_active"]

    def get_redeemable_centers(self, instance):
        qs = getattr(instance.program, "redeemable_center_preview", None)
        if qs is None:
            qs = instance.program.redeemable_centers.all()
        return MinimumCenterSerializer(qs[:5], many=True, context=self.context).data

    def create(self, validated_data):
        raise serializers.ValidationError("Create not allowed.")


class TherapyProgramDiscardSerializer(BaseModelSerializer):
    is_discarded = serializers.BooleanField(read_only=True)
    discarded_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = TherapyProgram
        fields = ["is_discarded", "discarded_by"]

    def create(self, validated_data: dict):
        therapy_program = validated_data["therapy_program"]
        if therapy_program.is_discarded:
            return therapy_program
        with transaction.atomic():
            discard_therapy_program(therapy_program, validated_data["discarded_by"])
        therapy_program.refresh_from_db(fields=["is_discarded", "discarded_by"])
        return therapy_program


class TherapyProgramCancelSerializer(BaseModelSerializer):
    cancellation_reason = serializers.CharField(
        source="program.cancellation_reason",
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    cancelled_by = BaseUserSerializer(source="program.cancelled_by", read_only=True)
    cancelled_at = serializers.DateTimeField(
        source="program.cancelled_at", read_only=True
    )
    cancelled_date = serializers.DateField(
        source="program.cancelled_date", required=False, default=timezone.localdate()
    )

    class Meta:
        model = TherapyProgram
        fields = [
            "cancellation_reason",
            "cancelled_by",
            "cancelled_date",
            "cancelled_at",
        ]

    def create(self, validated_data):
        center = validated_data.pop("center")
        therapy_program = validated_data.pop("therapy_program", None)
        cancelled_by = validated_data.pop("cancelled_by", None)
        program_fields = validated_data.pop("program", {})
        cancellation_reason = program_fields.get("cancellation_reason")
        cancelled_date = program_fields.get("cancelled_date")
        if not therapy_program:
            raise serializers.ValidationError("Not valid therapy program provided")
        if therapy_program.is_discarded:
            raise serializers.ValidationError("Discarded programs cannot be cancelled.")
        if not therapy_program.is_active:
            raise serializers.ValidationError("Program already cancelled")
        with transaction.atomic():
            Program.objects.filter(pk=therapy_program.program.pk).update(
                updated_at=timezone.localtime(),
            )
            if TherapyProgram.objects.filter(pk=therapy_program.pk, is_discarded=True).exists():
                raise serializers.ValidationError("Discarded programs cannot be cancelled.")
            therapy_program.is_active = False
            cancellation_fields = {
                "is_active": False,
                "cancellation_reason": cancellation_reason,
                "cancelled_by": cancelled_by,
                "cancelled_date": cancelled_date,
            }
            for field, value in cancellation_fields.items():
                create_program_audit_log(
                    therapy_program.program, field,
                    getattr(therapy_program.program, field), value, cancelled_by,
                )
                setattr(therapy_program.program, field, value)
            therapy_program.save(update_fields=["is_active"])
            therapy_program.program.save(
                update_fields=list(cancellation_fields)
            )
            cancel_all_program_services(
                therapy_program.program.pk,
                center_id=center.pk,
                cancelled_by=cancelled_by,
                cancellation_reason=cancellation_reason,
                cancelled_date=cancelled_date,
            )

        return therapy_program


class TherapyProgramRedeemSerializer(BaseModelSerializer):
    center_id = serializers.UUIDField(write_only=True)
    redeemed_date = serializers.DateField(required=False, default=timezone.localdate())

    class Meta:
        model = TherapyProgram
        fields = ["center_id", "redeemed_date"]

    def create(self, validated_data):
        therapy_program: TherapyProgram = validated_data.pop("therapy_program")
        redeemed_by = validated_data.pop("redeemed_by")
        center_id = validated_data["center_id"]
        redeemed_date = validated_data["redeemed_date"]
        if therapy_program.is_discarded:
            raise serializers.ValidationError("Discarded programs cannot be redeemed.")
        if not therapy_program.is_active:
            raise serializers.ValidationError("This program has been cancelled.")
        program_exists = (
            Program.objects.filter(pk=therapy_program.program.pk)
            .exclude(expires_at__lt=timezone.localdate())
            .exists()
        )
        if not program_exists:
            raise serializers.ValidationError("This program has expired.")

        if not ProgramService.objects.filter(
                program=therapy_program.program,
                is_active=True,
                service__center_assignments__center_id=center_id,
                service__center_assignments__is_active=True,
        ).exists():
            raise serializers.ValidationError(
                {"center_id": "This center does not offer any service in this program."}
            )

        redeemed = redeem_all_program_services(
            therapy_program.program.pk, center_id, redeemed_by, redeemed_date
        )
        if redeemed == 0:
            raise serializers.ValidationError(
                "No sessions remaining across any service in this program."
            )

        return therapy_program
