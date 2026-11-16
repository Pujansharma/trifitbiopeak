from datetime import date

from django.core.validators import RegexValidator
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.centers.models import Center
from accounts.centers.serializers import BaseCenterSerializer
from accounts.customers.models import CustomerProfile
from accounts.customers.serializers import (
    BaseCustomerProfileSerializer,
    CustomerProfileAddressSerializer,
)
from accounts.users.serializers import BaseUserSerializer
from accounts.users.utils.constants import Gender
from accounts.utils.auth import get_user_model
from accounts.utils.helper import get_date_of_birth_from_age
from core.utils.fields import PhoneNumberSerializerField
from core.utils.log import logger
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from integrations.metsights.utils.profiles import get_or_create_metsights_profile
from leads.models import Lead
from leads.utils.constants import (
    OpsOnboardingActionPriority,
    OpsOnboardingConsultationMode,
    OpsOnboardingPaymentStatus,
    OpsOnboardingTypeformStatus,
)
from leads.utils.db import (
    decrement_leads_assigned,
    decrement_leads_inactive,
    generate_lead_unique_id,
    increment_leads_assigned,
    increment_leads_inactive,
    increment_leads_total,
)
from leads.utils.helper import (
    USER_PHONE_EXISTS_ERROR,
    convert_lead_to_client,
    create_lead_composite_program,
    create_shell_customer_from_lead,
    sync_shell_from_lead,
)
from programs.composites.models import CompositeTemplate, CompositeTemplateService
from programs.composites.serializers import MinimumCompositeProgramTemplateSerializer
from programs.composites.validators import get_invalid_therapy_quantity_identifiers

User = get_user_model()

PAST_DATE_MESSAGE = "Date cannot be in the past"
RELATIONSHIP_LETTERS_ONLY_MESSAGE = "Relationship can only contain letters"
CONTACT_NAME_REQUIRED_MESSAGE = "Name is required"


class BaseLeadSerializer(BaseModelSerializer):
    phone = PhoneNumberSerializerField()
    customer_profile = BaseCustomerProfileSerializer(read_only=True)
    created_by = BaseUserSerializer(read_only=True)
    updated_by = BaseUserSerializer(read_only=True)
    home_center = BaseCenterSerializer(read_only=True)
    home_center_id = serializers.UUIDField(required=False, write_only=True)
    age = serializers.FloatField(required=True, write_only=True)
    gender = serializers.ChoiceField(choices=Gender.CHOICES, required=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "unique_id",
            "first_name",
            "last_name",
            "gender",
            "age",
            "date_of_birth",
            "phone",
            "email",
            "description",
            "is_active",
            "is_client",
            "is_invited",
            "is_joined",
            "is_onboarding_sent",
            "converted_on",
            "packages",
            "home_center",
            "home_center_id",
            "customer_profile",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "unique_id",
            "is_joined",
            "converted_on",
            "customer_profile",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]


class BaseLeadV2Serializer(BaseLeadSerializer):
    composite_program_template = MinimumCompositeProgramTemplateSerializer(
        read_only=True,
    )
    composite_template_id = serializers.UUIDField(
        source="composite_program_template",
        required=False,
        allow_null=True,
        write_only=True,
    )

    def validate_composite_template_id(self, value):
        if value is None:
            return None
        composite_template = CompositeTemplate.objects.filter_active(pk=value).first()
        if composite_template is None:
            raise serializers.ValidationError("Invalid or inactive composite template.")
        return composite_template


class LeadListCreateSerializer(BaseLeadSerializer):
    def post_create_lead(self, lead: Lead) -> None:
        return None

    def create(self, validated_data: dict) -> Lead:
        age = validated_data.pop("age", None)
        date_of_birth = validated_data.get("date_of_birth", None)
        phone = validated_data.get("phone")
        email = validated_data.get("email")
        first_name = validated_data.get("first_name")
        last_name = validated_data.get("last_name")
        gender = validated_data.get("gender")

        exists = Lead.objects.filter(phone__iexact=phone).exists()
        if exists:
            raise serializers.ValidationError({
                "phone": ["Lead with this phone number already exists."]
            })

        if age and not date_of_birth:
            date_of_birth = get_date_of_birth_from_age(age)
            validated_data["date_of_birth"] = date_of_birth

        validated_data["unique_id"] = generate_lead_unique_id()
        home_center_id = validated_data.pop("home_center_id", None)
        if home_center_id:
            home_center = Center.objects.filter(pk=home_center_id).first()
            if not home_center:
                raise serializers.ValidationError(
                    {"home_center_id": "Invalid center ID provided"}
                )
            validated_data["home_center"] = home_center

        with transaction.atomic():
            lead = super().create(validated_data)
            self.post_create_lead(lead)
            increment_leads_total()
            if not lead.is_active:
                increment_leads_inactive()
            metsights_profile_id = get_or_create_metsights_profile(
                phone=phone,
                email=email,
                first_name=first_name,
                last_name=last_name,
                gender=gender,
                age=age,
                date_of_birth=date_of_birth
            )
            if metsights_profile_id:
                lead.data = {
                    **(lead.data or {}),
                    "metsights_profile_id": metsights_profile_id,
                }
                lead.save(update_fields=["data"])
        return lead


class LeadV2ListCreateSerializer(BaseLeadV2Serializer, LeadListCreateSerializer):
    class Meta:
        model = Lead
        fields = [
            "id",
            "unique_id",
            "first_name",
            "last_name",
            "gender",
            "age",
            "date_of_birth",
            "phone",
            "email",
            "description",
            "is_active",
            "is_client",
            "is_invited",
            "is_joined",
            "is_onboarding_sent",
            "converted_on",
            "packages",
            "home_center",
            "home_center_id",
            "composite_program_template",
            "composite_template_id",
            "customer_profile",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "unique_id",
            "is_joined",
            "converted_on",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: dict):
        phone = validated_data.get("phone")
        if User.objects.filter(phone__iexact=phone).exists():
            raise serializers.ValidationError({
                "phone": [USER_PHONE_EXISTS_ERROR]
            })
        return super().create(validated_data)

    def post_create_lead(self, lead: Lead):
        try:
            create_shell_customer_from_lead(lead, created_by=lead.created_by)
        except ValueError as error:
            raise serializers.ValidationError({"phone": [str(error)]}) from error


class LeadDetailSerializer(BaseLeadSerializer):
    home_center_id = serializers.UUIDField(required=False)

    def should_sync_onboarding_sent_to_profile(self, lead: Lead) -> bool:
        return True

    def update(self, instance: Lead, validated_data: dict) -> Lead:
        was_active = instance.is_active
        was_joined = instance.is_joined
        was_onboarding_sent = instance.is_onboarding_sent
        was_converted = bool(instance.customer_profile or instance.converted_on)
        phone = validated_data.get("phone", instance.phone)
        exists = Lead.objects.exclude(pk=instance.pk).filter(
            phone__iexact=phone,
        ).exists()
        if exists:
            raise serializers.ValidationError({
                "phone": ["Lead with this phone number already exists."]
            })

        home_center_id = validated_data.pop("home_center_id", None)
        if home_center_id:
            home_center = Center.objects.filter(pk=home_center_id).first()
            if not home_center:
                raise serializers.ValidationError(
                    {"home_center_id": "Invalid center ID provided"}
                )
            validated_data["home_center"] = home_center
        age = validated_data.pop("age", None)
        date_of_birth = validated_data.get("date_of_birth", None)

        if age and not date_of_birth:
            date_of_birth = get_date_of_birth_from_age(age)
            validated_data["date_of_birth"] = date_of_birth
        with transaction.atomic():
            lead = super().update(instance, validated_data)
            lead_data = lead.data or {}
            if was_active and not lead.is_active:
                increment_leads_inactive()
            if not was_active and lead.is_active:
                decrement_leads_inactive()
            if not was_joined and lead.is_joined:
                increment_leads_assigned()
            if was_joined and not lead.is_joined and not was_converted:
                decrement_leads_assigned()
            if (
                    self.should_sync_onboarding_sent_to_profile(lead)
                    and lead.customer_profile_id is not None
                    and lead.is_onboarding_sent != was_onboarding_sent
            ):
                lead.customer_profile.is_onboarding_sent = lead.is_onboarding_sent
                lead.customer_profile.save(
                    update_fields=["is_onboarding_sent", "updated_at"]
                )
            if not lead_data.get("metsights_profile_id"):
                metsights_profile_id = get_or_create_metsights_profile(
                    phone=lead.phone,
                    email=lead.email,
                    first_name=lead.first_name,
                    last_name=lead.last_name,
                    gender=lead.gender,
                    age=None,
                    date_of_birth=lead.date_of_birth,
                )
                if metsights_profile_id:
                    lead.data = {
                        **lead_data,
                        "metsights_profile_id": metsights_profile_id,
                    }
                    lead.save(update_fields=["data"])
        return lead


class LeadCustomerProfileAddressSerializer(CustomerProfileAddressSerializer):
    class Meta(CustomerProfileAddressSerializer.Meta):
        fields = [
            "id",
            "label",
            "address_type",
            "address_type_code",
            "line_1",
            "line_2",
            "landmark",
            "city",
            "district",
            "state",
            "country",
            "pincode",
            "is_default",
        ]


class LeadCustomerProfileSerializer(BaseCustomerProfileSerializer):
    address = serializers.SerializerMethodField()

    class Meta(BaseCustomerProfileSerializer.Meta):
        fields = [
            *BaseCustomerProfileSerializer.Meta.fields,
            "address",
        ]

    def get_address(self, instance: CustomerProfile) -> dict | None:
        address = next(iter(instance.addresses.all()), None)
        if address is None:
            return None
        return LeadCustomerProfileAddressSerializer(
            address, context=self.context
        ).data


class LeadV2ListSerializer(LeadV2ListCreateSerializer):
    customer_profile = LeadCustomerProfileSerializer(read_only=True)


class LeadV2DetailSerializer(BaseLeadV2Serializer, LeadDetailSerializer):
    phone = PhoneNumberSerializerField(read_only=True)
    customer_profile = LeadCustomerProfileSerializer(read_only=True)

    class Meta:
        model = Lead
        fields = [
            "id",
            "unique_id",
            "first_name",
            "last_name",
            "gender",
            "age",
            "date_of_birth",
            "phone",
            "email",
            "description",
            "is_active",
            "is_client",
            "is_invited",
            "is_joined",
            "is_onboarding_sent",
            "converted_on",
            "packages",
            "home_center",
            "home_center_id",
            "composite_program_template",
            "composite_template_id",
            "customer_profile",
            "created_by",
            "updated_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "unique_id",
            "is_joined",
            "converted_on",
            "created_at",
            "updated_at",
        ]

    def should_sync_onboarding_sent_to_profile(self, lead: Lead):
        if lead.customer_profile is None:
            return True
        return lead.customer_profile.is_converted

    def update(self, instance: Lead, validated_data: dict):
        is_converted = instance.converted_on is not None or (
                instance.customer_profile is not None
                and instance.customer_profile.is_converted
        )
        if is_converted:
            allowed_fields = {"is_onboarding_sent", "updated_by"}
            disallowed_fields = set(validated_data.keys()) - allowed_fields
            if disallowed_fields:
                raise serializers.ValidationError(
                    "Only is_onboarding_sent is allowed to be updated after a lead is converted."
                )

        validated_data.pop("phone", None)
        with transaction.atomic():
            # Reject stale writes before the inherited update saves the whole lead.
            updated = Lead.objects.filter(
                pk=instance.pk,
                updated_at=instance.updated_at,
                converted_on=instance.converted_on,
            ).update(
                updated_at=timezone.localtime(),
                updated_by=validated_data.get("updated_by"),
            )
            if not updated:
                logger.warning(
                    f"LeadV2DetailSerializer.update: lead={instance.pk} "
                    f"reason=lead_changed"
                )
                raise serializers.ValidationError(
                    "Lead has changed. Refresh the lead before updating it."
                )
            lead = super().update(instance, validated_data)
            if not is_converted and lead.customer_profile is not None:
                sync_shell_from_lead(lead)
        return lead


class LeadConvertClientSerializer(BaseModelSerializer):
    class Meta:
        model = Lead
        fields = [
            "id",
            "is_client",
            "is_joined",
            "converted_on",
            "customer_profile",
        ]
        read_only_fields = fields

    def get_template_services(self, lead: Lead):
        if lead.composite_program_template is None:
            return []

        composite_template = lead.composite_program_template
        if not composite_template.is_active:
            raise serializers.ValidationError(
                {"composite_template_id": "Invalid or inactive composite template."}
            )
        template_services = list(
            CompositeTemplateService.objects.filter_active(
                composite_template=composite_template,
                service__is_active=True,
            ).select_related("service").order_by("created_at")
        )
        if not template_services:
            raise serializers.ValidationError(
                {"composite_template_id": "Composite template has no active services."}
            )

        service_quantities = []
        for template_service in template_services:
            service_quantities.append((template_service.service, template_service.quantity))
        invalid_quantity_identifiers = get_invalid_therapy_quantity_identifiers(
            service_quantities,
        )
        if invalid_quantity_identifiers:
            raise serializers.ValidationError(
                {
                    "composite_template_id": (
                        "A positive quantity is required for therapy services: "
                        f"{', '.join(sorted(invalid_quantity_identifiers))}."
                    )
                }
            )
        return template_services

    def create(self, validated_data: dict):
        lead = validated_data["lead"]
        updated_by = validated_data.get("updated_by")

        if lead.converted_on is not None or (
            lead.customer_profile is not None and lead.customer_profile.is_converted
        ):
            raise serializers.ValidationError("Lead is already converted to client.")
        if not lead.home_center:
            raise serializers.ValidationError(
                {"home_center": "Home center is required before conversion."}
            )
        template_services = self.get_template_services(lead)

        try:
            with transaction.atomic():
                # The version check also covers races with template and center edits.
                updated = Lead.objects.filter(
                    pk=lead.pk,
                    updated_at=lead.updated_at,
                    converted_on__isnull=True,
                ).update(updated_at=timezone.localtime(), updated_by=updated_by)
                if not updated:
                    logger.warning(
                        f"LeadConvertClientSerializer.create: lead={lead.pk} "
                        f"reason=lead_changed_or_converted"
                    )
                    raise serializers.ValidationError(
                        "Lead has changed or is already converted. Refresh the lead before converting it."
                    )
                customer_profile = convert_lead_to_client(lead, updated_by)
                if template_services:
                    create_lead_composite_program(
                        lead, customer_profile, template_services, updated_by,
                    )
        except ValueError as error:
            logger.warning(
                f"LeadConvertClientSerializer.create: lead={lead.pk} reason={error}"
            )
            raise serializers.ValidationError(str(error)) from error

        lead.refresh_from_db()
        return lead


def validate_not_past_date(value: date | None):
    if value and value < timezone.localdate():
        raise serializers.ValidationError(PAST_DATE_MESSAGE)
    return value

class OpsOnboardingAdditionalContactSerializer(BaseSerializer):
    name = serializers.CharField(required=False, allow_null=True, allow_blank=True)
    relationship = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
        validators=[RegexValidator(r"^[A-Za-z ]+$", RELATIONSHIP_LETTERS_ONLY_MESSAGE)],
    )
    email = serializers.EmailField(required=False, allow_null=True, allow_blank=True)
    phone = serializers.CharField(required=False, allow_null=True, allow_blank=True)

    def validate(self, attrs):
        has_contact_details = any(
            attrs.get(field) for field in ("relationship", "email", "phone")
        )
        if has_contact_details and not attrs.get("name"):
            raise serializers.ValidationError({"name": CONTACT_NAME_REQUIRED_MESSAGE})
        return attrs

class LeadOpsOnboardingEmailSerializer(BaseSerializer):
    package_value = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    payment_status = serializers.ChoiceField(
        choices=OpsOnboardingPaymentStatus.choices,
        required=False,
        allow_null=True,
    )
    therapy_paid_count = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    therapy_paid_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    therapy_complimentary_count = serializers.IntegerField(
        required=False, allow_null=True, min_value=0
    )
    therapy_complimentary_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    onboarding_status = serializers.ChoiceField(
        choices=OpsOnboardingTypeformStatus.choices,
        required=False,
        allow_null=True,
    )
    consultation_mode = serializers.ChoiceField(
        choices=OpsOnboardingConsultationMode.choices,
        required=False,
        allow_null=True,
    )
    preferred_consultation_date = serializers.DateField(
        required=False, allow_null=True
    )
    preferred_consultation_time = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    preferred_consultation_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    preferred_home_assessment_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    preferred_clinic_assessment_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    tentative_assessment_date = serializers.DateField(required=False, allow_null=True)
    test_kit_delivery = serializers.BooleanField(required=False, allow_null=True)
    special_instruction_notes = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    additional_contacts = OpsOnboardingAdditionalContactSerializer(
        many=True, required=False
    )
    action_note = serializers.CharField(
        required=False, allow_null=True, allow_blank=True
    )
    action_priority = serializers.ChoiceField(
        choices=OpsOnboardingActionPriority.choices,
        required=False,
        allow_null=True,
    )

    def validate_preferred_consultation_date(self, value):
        return validate_not_past_date(value)

    def validate_tentative_assessment_date(self, value):
        return validate_not_past_date(value)
