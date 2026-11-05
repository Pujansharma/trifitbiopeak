from collections.abc import Iterable
from datetime import date, datetime
from functools import partial

from django.db import IntegrityError, transaction
from django.db.models import Exists, F, Max, OuterRef
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import NotFound

from accounts.associates.models import AssociateRole
from accounts.associates.utils.roles import assignment_active_roles
from accounts.customers.models import CustomerProfile
from accounts.users.models import User
from accounts.users.utils.helper import calculate_age
from core.utils.exceptions import bad_request
from core.utils.models import BaseModelManager
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from supplementation.models import (
    Brand,
    Protocol,
    ProtocolAiJob,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
    Supplement,
    SupplementActiveIngredient,
    SupplementAllergen,
)
from supplementation.utils.constants import (
    AiRecommendationListStatus,
    AllergenName,
    AllergenPresenceType,
    DietaryAttribute,
    ProtocolAiJobStatus,
    ProtocolEventAction,
    ProtocolItemFrequency,
    ProtocolItemTiming,
    ProtocolVersionStatus,
    RawMaterialSourceType,
    SupplementForm,
)
from supplementation.utils.db import get_or_create_brand
from supplementation.utils.protocol_ai import (
    INACTIVE_SUPPLEMENT_DETAIL,
    accept_recommendation_item,
    apply_recommendation_item_modification,
    assert_item_open,
    create_protocol_draft,
    reject_recommendation_item,
)
from supplementation.utils.protocol_ai_wake import publish_protocol_ai_wake
from supplementation.utils.protocols import (
    summarize_current_protocols,
    version_supplement_count,
)
from supplementation.utils.version_status import (
    LIVE_PROTOCOL_VERSION_STATUSES,
    default_protocol_ends_on,
    is_protocol_one_active_violation,
    published_status,
    select_listed_protocol_version,
)


class SupplementAllergenListSerializer(serializers.ModelSerializer):
    """ModelSerializer so allergen codes stay stored values. Base* rewrites the label."""

    name = serializers.CharField()
    type = serializers.CharField(source="presence_type")

    class Meta:
        model = SupplementAllergen
        fields = ["name", "type"]


class SupplementMasterListSerializer(serializers.ModelSerializer):
    """ModelSerializer so form stays the stored code. Base* rewrites the label."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    form = serializers.CharField(read_only=True)
    allergen_information = SupplementAllergenListSerializer(
        source="allergens",
        many=True,
        read_only=True,
    )

    class Meta:
        model = Supplement
        fields = [
            "id",
            "product_name",
            "brand_name",
            "form",
            "dietary_attributes",
            "allergen_information",
        ]


class ActiveIngredientWriteSerializer(BaseSerializer):
    ingredient_name = serializers.CharField(max_length=255)
    serving = serializers.DecimalField(max_digits=12, decimal_places=4, min_value=0)
    unit = serializers.CharField(max_length=32)
    form = serializers.CharField(
        max_length=128,
        required=False,
        allow_blank=True,
        default="",
    )
    source = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )

    def validate_ingredient_name(self, value):
        cleaned_name = BaseModelManager.clean_spaces(value)
        if not cleaned_name:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_name


class AllergenWriteSerializer(BaseSerializer):
    name = serializers.ChoiceField(choices=AllergenName)
    type = serializers.ChoiceField(choices=AllergenPresenceType)


class ActiveIngredientReadSerializer(BaseModelSerializer):
    class Meta:
        model = SupplementActiveIngredient
        fields = [
            "ingredient_name",
            "serving",
            "unit",
            "form",
            "source",
        ]


class SupplementDetailSerializer(serializers.ModelSerializer):
    """ModelSerializer so choice codes stay stored values. Base* rewrites the label."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    form = serializers.CharField(read_only=True)
    raw_material_source_type = serializers.CharField(read_only=True)
    active_ingredients = ActiveIngredientReadSerializer(many=True, read_only=True)
    allergen_information = SupplementAllergenListSerializer(
        source="allergens",
        many=True,
        read_only=True,
    )

    class Meta:
        model = Supplement
        fields = [
            "id",
            "brand_name",
            "product_name",
            "form",
            "sku",
            "manufacturer",
            "raw_material_source_type",
            "pack_quantity_info",
            "serving_size",
            "serving_container",
            "market_country_code",
            "product_url",
            "dietary_attributes",
            "is_active",
            "active_ingredients",
            "allergen_information",
        ]


class BrandNameField(serializers.CharField):
    def get_attribute(self, instance):
        return instance.brand.name


class ActiveIngredientsField(serializers.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("default", list)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        serializer = ActiveIngredientWriteSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def to_representation(self, value):
        return ActiveIngredientReadSerializer(value.all(), many=True).data


class AllergenInformationField(serializers.Field):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("default", list)
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        serializer = AllergenWriteSerializer(data=data, many=True)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_attribute(self, instance):
        return instance.allergens

    def to_representation(self, value):
        return SupplementAllergenListSerializer(value.all(), many=True).data


class SupplementCreateSerializer(serializers.ModelSerializer):
    """ModelSerializer so choice codes stay stored values. Base* rewrites the label."""

    brand_name = BrandNameField(max_length=200)
    product_name = serializers.CharField(max_length=255)
    form = serializers.ChoiceField(choices=SupplementForm)
    sku = serializers.CharField(max_length=64)
    manufacturer = serializers.CharField(max_length=255)
    raw_material_source_type = serializers.ChoiceField(choices=RawMaterialSourceType)
    pack_quantity_info = serializers.CharField(max_length=255)
    serving_size = serializers.CharField(max_length=128)
    serving_container = serializers.IntegerField(min_value=1)
    market_country_code = serializers.RegexField(
        regex=r"^[A-Za-z]{2}$",
        max_length=2,
        min_length=2,
        error_messages={
            "invalid": "Enter a valid ISO 3166-1 alpha-2 country code.",
        },
    )
    product_url = serializers.URLField(required=False, allow_blank=True, default="")
    active_ingredients = ActiveIngredientsField()
    dietary_attributes = serializers.ListField(
        child=serializers.ChoiceField(choices=DietaryAttribute),
        required=False,
        default=list,
        allow_empty=True,
    )
    allergen_information = AllergenInformationField()

    class Meta:
        model = Supplement
        fields = [
            "id",
            "brand_name",
            "product_name",
            "form",
            "sku",
            "manufacturer",
            "raw_material_source_type",
            "pack_quantity_info",
            "serving_size",
            "serving_container",
            "market_country_code",
            "product_url",
            "active_ingredients",
            "dietary_attributes",
            "allergen_information",
        ]

    def validate_brand_name(self, value):
        cleaned_name = BaseModelManager.clean_spaces(value)
        if not cleaned_name:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_name

    def validate_product_name(self, value):
        cleaned_name = BaseModelManager.clean_spaces(value)
        if not cleaned_name:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_name

    def validate_sku(self, value):
        cleaned_sku = value.strip()
        if not cleaned_sku:
            raise serializers.ValidationError("This field may not be blank.")
        if Supplement.objects.filter(sku__iexact=cleaned_sku).exists():
            raise serializers.ValidationError(
                "A supplement with this SKU already exists."
            )
        return cleaned_sku

    def validate_manufacturer(self, value):
        cleaned_name = BaseModelManager.clean_spaces(value)
        if not cleaned_name:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_name

    def validate_market_country_code(self, value):
        return value.upper()

    def validate_dietary_attributes(self, value):
        return list(dict.fromkeys(value))

    def validate_allergen_information(self, value):
        allergen_names = [item["name"] for item in value]
        if len(allergen_names) != len(set(allergen_names)):
            raise serializers.ValidationError(
                "Duplicate allergen names are not allowed."
            )
        return value

    def validate(self, attrs):
        brand_name = attrs["brand_name"]
        product_name = attrs["product_name"]
        existing_brand = Brand.objects.filter(name__iexact=brand_name).first()
        if (
            existing_brand
            and Supplement.objects.filter(
                brand=existing_brand,
                product_name__iexact=product_name,
            ).exists()
        ):
            raise serializers.ValidationError(
                {
                    "product_name": [
                        "A supplement with this product name already exists for this brand."
                    ]
                }
            )
        return attrs

    def create(self, validated_data):
        active_ingredients = validated_data.pop("active_ingredients", [])
        allergen_information = validated_data.pop("allergen_information", [])
        brand_name = validated_data.pop("brand_name")
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            validated_data["created_by"] = request.user
        try:
            with transaction.atomic():
                brand = get_or_create_brand(brand_name)
                if Supplement.objects.filter(
                    brand=brand,
                    product_name__iexact=validated_data["product_name"],
                ).exists():
                    raise serializers.ValidationError(
                        {
                            "product_name": [
                                "A supplement with this product name already exists for this brand."
                            ]
                        }
                    )
                validated_data["brand"] = brand
                supplement = Supplement.objects.create(**validated_data)
                ingredient_rows = [
                    SupplementActiveIngredient(
                        supplement=supplement,
                        ingredient_name=item["ingredient_name"],
                        serving=item["serving"],
                        unit=item["unit"],
                        form=item.get("form", ""),
                        source=item.get("source", ""),
                        position=index,
                    )
                    for index, item in enumerate(active_ingredients)
                ]
                allergen_rows = [
                    SupplementAllergen(
                        supplement=supplement,
                        name=item["name"],
                        presence_type=item["type"],
                    )
                    for item in allergen_information
                ]
                if ingredient_rows:
                    SupplementActiveIngredient.objects.bulk_create(ingredient_rows)
                if allergen_rows:
                    SupplementAllergen.objects.bulk_create(allergen_rows)
        except IntegrityError as error:
            detail = supplement_unique_detail(error)
            if detail is None:
                raise
            raise serializers.ValidationError(detail)

        reloaded = (
            Supplement.objects.select_related("brand")
            .prefetch_related("active_ingredients", "allergens")
            .filter(pk=supplement.pk)
            .first()
        )
        if reloaded is None:
            raise NotFound("Supplement not found.")
        return reloaded


def iso_date(value: date | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def local_iso_date(value: datetime | None) -> str | None:
    if value is None:
        return None
    return timezone.localtime(value).date().isoformat()


def local_iso_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return timezone.localtime(value).isoformat()


def customer_profile_name(profile: CustomerProfile) -> str:
    name_parts = [
        name_part for name_part in (profile.first_name, profile.last_name) if name_part
    ]
    return " ".join(name_parts)


def customer_profile_age(profile: CustomerProfile) -> int | None:
    date_of_birth = profile.date_of_birth
    if date_of_birth is None or date_of_birth > timezone.localdate():
        return None
    return calculate_age(date_of_birth)


def customer_profile_gender(profile: CustomerProfile) -> str | None:
    if not profile.gender:
        return None
    return str(profile.get_gender_display())


class ProfileCardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()

    def get_name(self, profile: CustomerProfile) -> str:
        return customer_profile_name(profile)

    def get_gender(self, profile: CustomerProfile) -> str | None:
        return customer_profile_gender(profile)

    def get_age(self, profile: CustomerProfile) -> int | None:
        return customer_profile_age(profile)


class ProfileDetailCardSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.SerializerMethodField()
    contact_email = serializers.CharField(source="customer.contact_email")
    phone = serializers.SerializerMethodField()
    date_of_birth = serializers.DateField(allow_null=True)
    gender = serializers.SerializerMethodField()

    def get_name(self, profile: CustomerProfile) -> str:
        return customer_profile_name(profile)

    def get_phone(self, profile: CustomerProfile):
        return profile.customer.user.phone

    def get_gender(self, profile: CustomerProfile) -> str | None:
        return customer_profile_gender(profile)


class ConstraintSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    kind = serializers.CharField()
    name = serializers.CharField()
    severity = serializers.CharField(allow_null=True)
    notes = serializers.CharField(allow_null=True, allow_blank=True)
    is_active = serializers.BooleanField()


class ActiveProtocolSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    purpose = serializers.CharField()
    version_id = serializers.UUIDField(source="current_version.id")
    version_number = serializers.IntegerField(source="current_version.version_number")
    status = serializers.SerializerMethodField()
    starts_on = serializers.DateField(source="current_version.starts_on", allow_null=True)
    ends_on = serializers.DateField(source="current_version.ends_on", allow_null=True)
    review_on = serializers.DateField(source="current_version.review_on", allow_null=True)

    def get_status(self, protocol: Protocol) -> str:
        return "active"


class ProtocolVersionHeaderSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    status = serializers.CharField()
    starts_on = serializers.DateField(allow_null=True)
    ends_on = serializers.DateField(allow_null=True)
    review_on = serializers.DateField(allow_null=True)
    supplement_count = serializers.SerializerMethodField()

    def get_supplement_count(self, version: ProtocolVersion) -> int:
        return version_supplement_count(version)


def protocol_version_name(version_number: int) -> str:
    return f"v{version_number}"


class PlanSummarySerializer(BaseSerializer):
    active = serializers.IntegerField(read_only=True)
    coming_up = serializers.IntegerField(read_only=True)
    preparing = serializers.IntegerField(read_only=True)
    historical = serializers.IntegerField(read_only=True)


class SupplementationProfileListSerializer(serializers.Serializer):
    customer_profile = ProfileCardSerializer(source="*")
    constraints = ConstraintSerializer(source="supplement_constraints", many=True)
    last_updated_on = serializers.SerializerMethodField()
    protocols = serializers.SerializerMethodField()

    def get_last_updated_on(self, profile: CustomerProfile) -> str | None:
        return local_iso_date(profile.plan_updated_at)

    def get_protocols(self, profile: CustomerProfile) -> dict[str, object]:
        active_protocol, coming_up_count, historical_counts = (
            summarize_current_protocols(
                profile.supplement_protocols.all(),
                timezone.localdate(),
            )
        )
        active_protocol_data = None
        if active_protocol is not None:
            active_protocol_data = ActiveProtocolSerializer(active_protocol).data
        return {
            "active_protocol": active_protocol_data,
            "coming_up_count": coming_up_count,
            "historical_counts": historical_counts,
        }


class SupplementationProfileDetailSerializer(serializers.Serializer):
    customer_profile = ProfileDetailCardSerializer(source="*")
    constraints = ConstraintSerializer(source="supplement_constraints", many=True)
    protocol_count = serializers.IntegerField()


def scratch_protocol_fields(validated_data, source_version):
    return {
        "name": validated_data["name"],
        "purpose": validated_data["purpose"],
    }


def copied_protocol_fields(validated_data, source_version):
    return {
        "name": validated_data.get("name", source_version.protocol.name),
        "purpose": validated_data.get("purpose", source_version.protocol.purpose),
    }


def protocol_fields(validated_data):
    source_version = validated_data.get("source_version")
    field_builders = {
        True: copied_protocol_fields,
        False: scratch_protocol_fields,
    }
    return field_builders[source_version is not None](validated_data, source_version)


def scratch_protocol_version_fields(validated_data, source_version):
    return {
        "notes": validated_data.get("notes", ""),
        "summary_notes": None,
        "is_ongoing": False,
    }


def copied_protocol_version_fields(validated_data, source_version):
    notes = source_version.notes
    if "notes" in validated_data:
        notes = validated_data["notes"]
    return {
        "notes": notes,
        "summary_notes": source_version.summary_notes,
        "is_ongoing": source_version.is_ongoing,
    }


def protocol_version_fields(validated_data):
    source_version = validated_data.get("source_version")
    field_builders = {
        True: copied_protocol_version_fields,
        False: scratch_protocol_version_fields,
    }
    return field_builders[source_version is not None](validated_data, source_version)


def version_drafted_after(version, source_version):
    after = {
        "version_number": version.version_number,
        "status": version.status,
    }
    if source_version is not None:
        after["source_version_id"] = str(source_version.id)
    return after


class ProtocolCreateSerializer(BaseSerializer):
    source_version_id = serializers.UUIDField(required=False)
    name = serializers.CharField(max_length=255, required=False)
    purpose = serializers.CharField(required=False)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        if "source_version_id" not in attrs:
            missing = {
                field_name: ["This field is required."]
                for field_name in ("name", "purpose")
                if field_name not in attrs
            }
            if missing:
                raise serializers.ValidationError(missing)
            return attrs
        source_version = (
            ProtocolVersion.objects.select_related("protocol")
            .filter(
                pk=attrs["source_version_id"],
                protocol__customer_profile=self.context["customer_profile"],
            )
            .first()
        )
        if source_version is None:
            raise NotFound("Protocol version not found.")
        attrs["source_version"] = source_version
        return attrs

    def create(self, validated_data):
        profile = self.context["customer_profile"]
        actor = self.context["request"].user
        source_version = validated_data.get("source_version")
        version_fields = protocol_version_fields(validated_data)
        with transaction.atomic():
            protocol = Protocol.objects.create(
                customer_profile=profile,
                created_by=actor,
                **protocol_fields(validated_data),
            )
            version = ProtocolVersion.objects.create(
                protocol=protocol,
                version_number=1,
                status=ProtocolVersionStatus.DRAFT,
                **version_fields,
            )
            ProtocolEvent.objects.bulk_create(
                [
                    ProtocolEvent(
                        customer_profile=profile,
                        protocol=protocol,
                        protocol_version=version,
                        actor=actor,
                        action=ProtocolEventAction.PROTOCOL_CREATED,
                        after={
                            "name": protocol.name,
                            "purpose": protocol.purpose,
                        },
                        client_visible=False,
                    ),
                    ProtocolEvent(
                        customer_profile=profile,
                        protocol=protocol,
                        protocol_version=version,
                        actor=actor,
                        action=ProtocolEventAction.VERSION_DRAFTED,
                        after=version_drafted_after(version, source_version),
                        client_visible=False,
                    ),
                ]
            )
        return protocol


SUPPLEMENT_UNIQUE_MESSAGES = {
    "uniq_supplement_sku": {
        "sku": ["A supplement with this SKU already exists."],
    },
    "uniq_supplement_brand_product_name": {
        "product_name": [
            "A supplement with this product name already exists for this brand."
        ],
    },
}
PROTOCOL_VERSION_INSERT_ATTEMPTS = 5
PROTOCOL_VERSION_NUMBER_CONSTRAINT = "uniq_protocol_version_no"


def supplement_unique_detail(error: IntegrityError):
    message = str(error)
    for constraint_name, detail in SUPPLEMENT_UNIQUE_MESSAGES.items():
        if constraint_name in message:
            return detail
    return None


def is_protocol_version_number_violation(error: IntegrityError):
    return PROTOCOL_VERSION_NUMBER_CONSTRAINT in str(error)


COPYABLE_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.APPROVED,
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.ACTIVE,
    ProtocolVersionStatus.SUPERSEDED,
    ProtocolVersionStatus.EXPIRED,
    ProtocolVersionStatus.CANCELLED,
)


def next_protocol_version_number(protocol: Protocol) -> int:
    latest_number = protocol.versions.aggregate(latest_number=Max("version_number"))[
        "latest_number"
    ]
    if latest_number is None:
        return 1
    return latest_number + 1


def clone_protocol_items(
    source_version: ProtocolVersion,
    version: ProtocolVersion,
) -> None:
    source_items = list(source_version.items.select_related("supplement"))
    if any(not item.supplement.is_active for item in source_items):
        raise serializers.ValidationError(
            {"source_version_id": [INACTIVE_SUPPLEMENT_DETAIL]}
        )
    ProtocolItem.objects.bulk_create(
        [
            ProtocolItem(
                version=version,
                supplement_id=item.supplement_id,
                dosage=item.dosage,
                frequency=item.frequency,
                custom_frequency=item.custom_frequency,
                timing=item.timing,
                duration=item.duration,
                instructions=item.instructions,
                rationale=item.rationale,
            )
            for item in source_items
        ]
    )


def insert_draft_protocol_version(protocol, actor, summary_notes, source_version):
    with transaction.atomic():
        version = ProtocolVersion.objects.create(
            protocol=protocol,
            version_number=next_protocol_version_number(protocol),
            status=ProtocolVersionStatus.DRAFT,
            notes=None,
            summary_notes=summary_notes,
            is_ongoing=False,
        )
        if source_version is not None:
            clone_protocol_items(source_version, version)
        ProtocolEvent.objects.create(
            customer_profile=protocol.customer_profile,
            protocol=protocol,
            protocol_version=version,
            actor=actor,
            action=ProtocolEventAction.VERSION_DRAFTED,
            after=version_drafted_after(version, source_version),
            client_visible=False,
        )
    return version


def create_next_draft_protocol_version(protocol, actor, summary_notes, source_version):
    attempt_number = 0
    while attempt_number < PROTOCOL_VERSION_INSERT_ATTEMPTS:
        attempt_number += 1
        try:
            return insert_draft_protocol_version(
                protocol,
                actor,
                summary_notes,
                source_version,
            )
        except IntegrityError as error:
            if not is_protocol_version_number_violation(error):
                raise
    bad_request("Could not allocate a protocol version number.")


class ProtocolVersionCreateSerializer(BaseSerializer):
    source_version_id = serializers.UUIDField(required=False, write_only=True)
    summary_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        write_only=True,
    )
    new_protocol_version_id = serializers.UUIDField(source="pk", read_only=True)

    def validate(self, attrs):
        summary_notes = attrs.get("summary_notes", "")
        attrs["summary_notes"] = summary_notes.strip() or None
        if "source_version_id" not in attrs:
            return attrs
        protocol = self.context["protocol"]
        source_version = ProtocolVersion.objects.filter(
            pk=attrs["source_version_id"],
            protocol__customer_profile=protocol.customer_profile,
        ).first()
        if source_version is None:
            raise NotFound("Protocol version not found.")
        if source_version.status not in COPYABLE_PROTOCOL_VERSION_STATUSES:
            bad_request("Protocol version can only be copied once it is approved.")
        attrs["source_version"] = source_version
        return attrs

    def create(self, validated_data):
        return create_next_draft_protocol_version(
            self.context["protocol"],
            self.context["request"].user,
            validated_data["summary_notes"],
            validated_data.get("source_version"),
        )


class ProtocolDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    purpose = serializers.CharField()
    current_version_id = serializers.UUIDField(allow_null=True)
    versions = ProtocolVersionHeaderSerializer(many=True)


class ProtocolCurrentVersionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    current_version_id = serializers.SerializerMethodField()
    version_name = serializers.SerializerMethodField()
    supplement_count = serializers.SerializerMethodField()
    effective_from = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    def listed_version(self, protocol: Protocol) -> ProtocolVersion:
        cached = getattr(protocol, "_listed_protocol_version", None)
        if cached is None:
            versions = list(protocol.versions.all())
            if len(versions) == 1:
                cached = versions[0]
            else:
                cached = select_listed_protocol_version(versions)
            protocol._listed_protocol_version = cached
        return cached

    def get_current_version_id(self, protocol: Protocol) -> str:
        return str(self.listed_version(protocol).id)

    def get_version_name(self, protocol: Protocol) -> str:
        return protocol_version_name(self.listed_version(protocol).version_number)

    def get_supplement_count(self, protocol: Protocol) -> int:
        return version_supplement_count(self.listed_version(protocol))

    def get_effective_from(self, protocol: Protocol) -> str | None:
        return iso_date(self.listed_version(protocol).starts_on)

    def get_status(self, protocol: Protocol) -> str:
        return self.listed_version(protocol).status


class ProtocolItemSupplementSerializer(serializers.ModelSerializer):
    """ModelSerializer so form stays the stored code. Base* rewrites the label."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    form = serializers.CharField(read_only=True)

    class Meta:
        model = Supplement
        fields = ["id", "product_name", "brand_name", "form"]


class AiRecommendationSupplementSerializer(serializers.ModelSerializer):
    """ModelSerializer so form stays the stored code. Base* rewrites the label."""

    brand_name = serializers.CharField(source="brand.name", read_only=True)
    form = serializers.CharField(read_only=True)

    class Meta:
        model = Supplement
        fields = [
            "id",
            "product_name",
            "brand_name",
            "form",
            "manufacturer",
        ]


class PlanRoutineItemSerializer(BaseModelSerializer):
    supplement = ProtocolItemSupplementSerializer(read_only=True)
    ends_on = serializers.DateField(
        source="version.ends_on",
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = ProtocolItem
        fields = [
            "id",
            "supplement",
            "dosage",
            "frequency",
            "custom_frequency",
            "timing",
            "ends_on",
            "instructions",
            "rationale",
        ]


class PlanRoutineSlotSerializer(BaseSerializer):
    timing = serializers.CharField()
    items = PlanRoutineItemSerializer(many=True)


class PlanRoutineSerializer(BaseSerializer):
    timings = PlanRoutineSlotSerializer(many=True)


class PlanProtocolSupplementSerializer(BaseModelSerializer):
    supplement = ProtocolItemSupplementSerializer(read_only=True)

    class Meta:
        model = ProtocolItem
        fields = [
            "id",
            "supplement",
            "dosage",
            "frequency",
            "custom_frequency",
            "timing",
            "duration",
            "instructions",
            "rationale",
        ]


class PlanProtocolVersionSerializer(BaseSerializer):
    id = serializers.UUIDField()
    version_number = serializers.IntegerField()
    starts_on = serializers.DateField(allow_null=True)
    ends_on = serializers.DateField(allow_null=True)


class PlanProtocolRowSerializer(BaseSerializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    purpose = serializers.CharField()
    status = serializers.CharField()
    supplement_count = serializers.IntegerField()
    version = PlanProtocolVersionSerializer()
    supplements = PlanProtocolSupplementSerializer(many=True)


class PlanProtocolSummarySerializer(BaseSerializer):
    active = serializers.IntegerField()
    scheduled = serializers.IntegerField()
    draft = serializers.IntegerField()
    cancelled = serializers.IntegerField()
    expired = serializers.IntegerField()


class PlanProtocolsSerializer(BaseSerializer):
    summary = PlanProtocolSummarySerializer()
    active = PlanProtocolRowSerializer(many=True)
    scheduled = PlanProtocolRowSerializer(many=True)
    cancelled = PlanProtocolRowSerializer(many=True)
    expired = PlanProtocolRowSerializer(many=True)


class PlanSupplementIdentitySerializer(BaseSerializer):
    id = serializers.UUIDField()
    product_name = serializers.CharField()
    brand_name = serializers.CharField()
    form = serializers.CharField()


class PlanSupplementDosingSerializer(BaseSerializer):
    dosage = serializers.CharField()
    frequency = serializers.CharField()
    custom_frequency = serializers.CharField(allow_null=True)
    timing = serializers.CharField()
    instructions = serializers.CharField()
    rationale = serializers.CharField()


class PlanModifiedChangeSerializer(BaseSerializer):
    supplement = PlanSupplementIdentitySerializer()
    before = PlanSupplementDosingSerializer()
    after = PlanSupplementDosingSerializer()


class PlanSupplementSnapshotSerializer(BaseSerializer):
    supplement = PlanSupplementIdentitySerializer()
    dosage = serializers.CharField()
    frequency = serializers.CharField()
    custom_frequency = serializers.CharField(allow_null=True)
    timing = serializers.CharField()
    instructions = serializers.CharField()
    rationale = serializers.CharField()


class PlanReplacedChangeSerializer(BaseSerializer):
    before = PlanSupplementSnapshotSerializer()
    after = PlanSupplementSnapshotSerializer()


class PlanChangeBucketsSerializer(BaseSerializer):
    modified = PlanModifiedChangeSerializer(many=True)
    replaced = PlanReplacedChangeSerializer(many=True)
    added = PlanSupplementSnapshotSerializer(many=True)
    removed = PlanSupplementSnapshotSerializer(many=True)


class PlanSupplementChangeSerializer(BaseSerializer):
    name = serializers.CharField()
    status = serializers.CharField()
    changes = PlanChangeBucketsSerializer()


def missing_protocol_item_supplement(supplement_id: str) -> dict[str, object]:
    return {
        "id": supplement_id,
        "product_name": None,
        "brand_name": None,
        "form": None,
    }


def supplement_ids_in_events(events: Iterable[ProtocolEvent]) -> set[str]:
    return {
        str(snapshot["supplement_id"])
        for event in events
        for snapshot in (event.before, event.after)
        if isinstance(snapshot, dict) and snapshot.get("supplement_id")
    }


def load_event_supplements(
    events: Iterable[ProtocolEvent],
) -> dict[str, dict[str, object]]:
    supplement_ids = supplement_ids_in_events(events)
    if not supplement_ids:
        return {}
    supplements = Supplement.objects.filter(pk__in=supplement_ids).select_related(
        "brand"
    )
    rows = ProtocolItemSupplementSerializer(supplements, many=True).data
    return {row["id"]: row for row in rows}


def present_event_snapshot(
    snapshot: object,
    event_supplements: dict[str, dict[str, object]],
) -> object:
    if not isinstance(snapshot, dict) or "supplement_id" not in snapshot:
        return snapshot
    supplement_id = str(snapshot["supplement_id"])
    presented = {
        key: value for key, value in snapshot.items() if key != "supplement_id"
    }
    presented["supplement"] = event_supplements.get(
        supplement_id,
        missing_protocol_item_supplement(supplement_id),
    )
    return presented


class SupplementationProfileEventListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        events = list(data)
        self.context["event_supplements"] = load_event_supplements(events)
        return [self.child.to_representation(event) for event in events]


class LocalIsoDateTimeField(serializers.DateTimeField):
    def to_representation(self, value):
        return local_iso_datetime(value)


def protocol_event_actor_roles(user: User) -> list[AssociateRole]:
    associate = getattr(user, "associate", None)
    if associate is None:
        return []
    roles = []
    seen_role_ids = set()
    for assignment in associate.center_assignments.all():
        for role in assignment_active_roles(assignment):
            if role.pk in seen_role_ids:
                continue
            seen_role_ids.add(role.pk)
            roles.append(role)
    return roles


class ProtocolEventActorRoleSerializer(BaseModelSerializer):
    class Meta:
        model = AssociateRole
        fields = ["id", "name"]


class ProtocolEventActorSerializer(BaseSerializer):
    name = serializers.SerializerMethodField()
    roles = serializers.SerializerMethodField()

    def get_name(self, user: User) -> str:
        name_parts = [
            name_part
            for name_part in (user.first_name, user.last_name)
            if name_part
        ]
        return " ".join(name_parts)

    def get_roles(self, user: User) -> list:
        return ProtocolEventActorRoleSerializer(
            protocol_event_actor_roles(user),
            many=True,
        ).data


class SupplementationProfileEventSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action = serializers.CharField()
    actor = ProtocolEventActorSerializer(allow_null=True)
    reason = serializers.CharField(allow_null=True, allow_blank=True)
    client_visible = serializers.BooleanField()
    client_title = serializers.CharField(allow_null=True, allow_blank=True)
    change_type = serializers.CharField(allow_null=True, allow_blank=True)
    effective_on = serializers.DateField(allow_null=True)
    protocol_id = serializers.SerializerMethodField()
    protocol_name = serializers.SerializerMethodField()
    protocol_version_id = serializers.SerializerMethodField()
    protocol_version_number = serializers.SerializerMethodField()
    before = serializers.SerializerMethodField()
    after = serializers.SerializerMethodField()
    created_at = LocalIsoDateTimeField()

    class Meta:
        list_serializer_class = SupplementationProfileEventListSerializer

    def event_supplements(self, event: ProtocolEvent) -> dict[str, dict[str, object]]:
        supplements = self.context.get("event_supplements")
        if supplements is None:
            return load_event_supplements([event])
        return supplements

    def get_protocol_id(self, event: ProtocolEvent) -> str | None:
        if event.protocol is None:
            return None
        return str(event.protocol.pk)

    def get_protocol_name(self, event: ProtocolEvent) -> str | None:
        if event.protocol is None:
            return None
        return event.protocol.name

    def get_protocol_version_id(self, event: ProtocolEvent) -> str | None:
        if event.protocol_version is None:
            return None
        return str(event.protocol_version.pk)

    def get_protocol_version_number(self, event: ProtocolEvent) -> int | None:
        if event.protocol_version is None:
            return None
        return event.protocol_version.version_number

    def get_before(self, event: ProtocolEvent):
        return present_event_snapshot(event.before, self.event_supplements(event))

    def get_after(self, event: ProtocolEvent):
        return present_event_snapshot(event.after, self.event_supplements(event))


APPROVABLE_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.DRAFT,
    ProtocolVersionStatus.UNDER_REVIEW,
)
CANCELLABLE_PROTOCOL_VERSION_STATUSES = (
    ProtocolVersionStatus.APPROVED,
    ProtocolVersionStatus.SCHEDULED,
    ProtocolVersionStatus.ACTIVE,
)


def protocol_version_window_payload(version):
    return {
        "status": version.status,
        "starts_on": iso_date(version.starts_on),
        "ends_on": iso_date(version.ends_on),
        "approval_notes": version.approval_notes,
    }


def protocol_item_payload(item):
    return {
        "supplement_id": str(item.supplement.pk),
        "dosage": item.dosage,
        "frequency": item.frequency,
        "custom_frequency": item.custom_frequency,
        "timing": item.timing,
        "duration": item.duration,
        "instructions": item.instructions,
        "rationale": item.rationale,
    }


EDITABLE_PROTOCOL_ITEM_STATUSES = (
    ProtocolVersionStatus.DRAFT,
    ProtocolVersionStatus.UNDER_REVIEW,
)
PROTOCOL_ITEM_LOCKED_DETAIL = (
    "Supplements can only be changed while the version is draft or under review."
)


def assert_protocol_item_editable(version):
    if version.status not in EDITABLE_PROTOCOL_ITEM_STATUSES:
        bad_request(PROTOCOL_ITEM_LOCKED_DETAIL)


def claim_protocol_version_status(version, statuses, detail):
    claimed = ProtocolVersion.objects.filter(
        pk=version.pk,
        status__in=statuses,
    ).update(updated_at=F("updated_at"))
    if claimed == 0:
        bad_request(detail)


def protocol_version_has_items():
    return Exists(ProtocolItem.objects.filter(version=OuterRef("pk")))


def protocol_version_has_inactive_supplement():
    return Exists(
        ProtocolItem.objects.filter(
            version=OuterRef("pk"),
            supplement__is_active=False,
        )
    )


def version_has_inactive_supplement(version):
    return version.items.filter(supplement__is_active=False).exists()


def reject_failed_protocol_approve(version):
    current_status = (
        ProtocolVersion.objects.filter(pk=version.pk)
        .values_list("status", flat=True)
        .first()
    )
    if current_status in APPROVABLE_PROTOCOL_VERSION_STATUSES:
        if version_has_inactive_supplement(version):
            bad_request(INACTIVE_SUPPLEMENT_DETAIL)
        bad_request("Add at least one supplement before approving this version.")
    bad_request(
        "Protocol version can only be approved while it is draft or under review."
    )


def reject_failed_protocol_publish(version):
    current_status = (
        ProtocolVersion.objects.filter(pk=version.pk)
        .values_list("status", flat=True)
        .first()
    )
    if current_status == ProtocolVersionStatus.APPROVED:
        if version_has_inactive_supplement(version):
            bad_request(INACTIVE_SUPPLEMENT_DETAIL)
        bad_request("Add at least one supplement before publishing this version.")
    bad_request("Protocol version can only be published while it is approved.")


def reject_mismatched_version_id(version_id, version):
    if version_id != version.pk:
        raise serializers.ValidationError(
            {"version_id": ["version_id does not match this protocol version."]}
        )


DUPLICATE_PROTOCOL_SUPPLEMENT_DETAIL = "This supplement is already on this version."
UNIQ_PROTOCOL_ITEM_VERSION_SUPPLEMENT = "uniq_protocol_item_version_supplement"


def active_supplement(supplement_id):
    supplement = (
        Supplement.objects.select_related("brand").filter(pk=supplement_id).first()
    )
    if supplement is None:
        raise NotFound("Supplement not found.")
    if not supplement.is_active:
        raise serializers.ValidationError(
            {"supplement_id": ["Supplement is inactive."]}
        )
    return supplement


def raise_duplicate_protocol_supplement():
    raise serializers.ValidationError(
        {"supplement_id": [DUPLICATE_PROTOCOL_SUPPLEMENT_DETAIL]}
    )


def reject_duplicate_protocol_supplement(version, supplement_id, protocol_item=None):
    existing_items = version.items.filter(supplement=supplement_id)
    if protocol_item is not None:
        existing_items = existing_items.exclude(pk=protocol_item.pk)
    if existing_items.exists():
        raise_duplicate_protocol_supplement()


def is_protocol_item_supplement_unique_violation(error: IntegrityError):
    return UNIQ_PROTOCOL_ITEM_VERSION_SUPPLEMENT in str(error)


def clean_custom_frequency(frequency, custom_frequency):
    if isinstance(custom_frequency, str):
        custom_frequency = custom_frequency.strip() or None
    if frequency == ProtocolItemFrequency.CUSTOM:
        if custom_frequency is None:
            raise serializers.ValidationError(
                {
                    "custom_frequency": [
                        "This field is required when frequency is custom."
                    ]
                }
            )
        return custom_frequency
    if custom_frequency is not None:
        raise serializers.ValidationError(
            {
                "custom_frequency": [
                    "custom_frequency must be null unless frequency is custom."
                ]
            }
        )
    return None


def assign_protocol_item_dosing(item, validated_data):
    item.dosage = validated_data["dosage"]
    item.frequency = validated_data["frequency"]
    item.custom_frequency = validated_data["custom_frequency"]
    item.timing = validated_data["timing"]
    item.duration = validated_data["duration"]
    item.instructions = validated_data["instructions"]


class ProtocolItemSerializer(BaseModelSerializer):
    version_id = serializers.UUIDField()
    supplement_id = serializers.UUIDField(write_only=True)
    supplement = ProtocolItemSupplementSerializer(read_only=True)
    frequency = serializers.ChoiceField(choices=ProtocolItemFrequency.choices)
    timing = serializers.ChoiceField(choices=ProtocolItemTiming.choices)
    custom_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    class Meta:
        model = ProtocolItem
        fields = [
            "id",
            "version_id",
            "supplement_id",
            "supplement",
            "dosage",
            "frequency",
            "custom_frequency",
            "timing",
            "duration",
            "instructions",
            "rationale",
        ]

    def validate(self, attrs):
        version = self.context["version"]
        reject_mismatched_version_id(attrs["version_id"], version)
        if version.status != ProtocolVersionStatus.DRAFT:
            raise serializers.ValidationError(
                {
                    "version_id": [
                        "Supplements can only be added while the version is draft."
                    ]
                }
            )
        attrs["supplement"] = active_supplement(attrs["supplement_id"])
        reject_duplicate_protocol_supplement(version, attrs["supplement"].pk)
        attrs["custom_frequency"] = clean_custom_frequency(
            attrs["frequency"],
            attrs.get("custom_frequency"),
        )
        return attrs

    def create(self, validated_data):
        version = self.context["version"]
        actor = self.context["request"].user
        validated_data.pop("version_id")
        validated_data.pop("supplement_id")
        try:
            with transaction.atomic():
                claim_protocol_version_status(
                    version,
                    (ProtocolVersionStatus.DRAFT,),
                    "Supplements can only be added while the version is draft.",
                )
                item = ProtocolItem.objects.create(version=version, **validated_data)
                record_protocol_version_event(
                    version,
                    actor,
                    ProtocolEventAction.SUPPLEMENT_ADDED,
                    None,
                    protocol_item_payload(item),
                    False,
                )
        except IntegrityError as error:
            if not is_protocol_item_supplement_unique_violation(error):
                raise
            raise_duplicate_protocol_supplement()
        return item


class ProtocolItemUpdateSerializer(BaseModelSerializer):
    version_id = serializers.UUIDField(read_only=True)
    supplement = ProtocolItemSupplementSerializer(read_only=True)
    frequency = serializers.ChoiceField(choices=ProtocolItemFrequency.choices)
    timing = serializers.ChoiceField(choices=ProtocolItemTiming.choices)
    custom_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    rationale = serializers.CharField(read_only=True)
    reason = serializers.CharField(write_only=True)

    class Meta:
        model = ProtocolItem
        fields = [
            "id",
            "version_id",
            "supplement",
            "dosage",
            "frequency",
            "custom_frequency",
            "timing",
            "duration",
            "instructions",
            "rationale",
            "reason",
        ]

    def validate(self, attrs):
        assert_protocol_item_editable(self.instance.version)
        attrs["custom_frequency"] = clean_custom_frequency(
            attrs["frequency"],
            attrs.get("custom_frequency"),
        )
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        before = protocol_item_payload(instance)
        with transaction.atomic():
            claim_protocol_version_status(
                instance.version,
                EDITABLE_PROTOCOL_ITEM_STATUSES,
                PROTOCOL_ITEM_LOCKED_DETAIL,
            )
            assign_protocol_item_dosing(instance, validated_data)
            instance.save()
            record_protocol_version_event(
                instance.version,
                actor,
                ProtocolEventAction.SUPPLEMENT_MODIFIED,
                before,
                protocol_item_payload(instance),
                False,
                reason=validated_data["reason"],
            )
        return instance


class ProtocolItemReplaceSerializer(BaseModelSerializer):
    version_id = serializers.UUIDField()
    supplement_id = serializers.UUIDField(write_only=True)
    supplement = ProtocolItemSupplementSerializer(read_only=True)
    frequency = serializers.ChoiceField(choices=ProtocolItemFrequency.choices)
    timing = serializers.ChoiceField(choices=ProtocolItemTiming.choices)
    custom_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    class Meta:
        model = ProtocolItem
        fields = [
            "id",
            "version_id",
            "supplement_id",
            "supplement",
            "dosage",
            "frequency",
            "custom_frequency",
            "timing",
            "duration",
            "instructions",
            "rationale",
        ]

    def validate(self, attrs):
        version = self.instance.version
        assert_protocol_item_editable(version)
        reject_mismatched_version_id(attrs["version_id"], version)
        attrs["supplement"] = active_supplement(attrs["supplement_id"])
        reject_duplicate_protocol_supplement(
            version,
            attrs["supplement"].pk,
            protocol_item=self.instance,
        )
        attrs["custom_frequency"] = clean_custom_frequency(
            attrs["frequency"],
            attrs.get("custom_frequency"),
        )
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        before = protocol_item_payload(instance)
        try:
            with transaction.atomic():
                claim_protocol_version_status(
                    instance.version,
                    EDITABLE_PROTOCOL_ITEM_STATUSES,
                    PROTOCOL_ITEM_LOCKED_DETAIL,
                )
                instance.supplement = validated_data["supplement"]
                assign_protocol_item_dosing(instance, validated_data)
                instance.rationale = validated_data["rationale"]
                instance.save()
                record_protocol_version_event(
                    instance.version,
                    actor,
                    ProtocolEventAction.SUPPLEMENT_REPLACED,
                    before,
                    protocol_item_payload(instance),
                    False,
                )
        except IntegrityError as error:
            if not is_protocol_item_supplement_unique_violation(error):
                raise
            raise_duplicate_protocol_supplement()
        return instance


class ProtocolItemDeleteSerializer(BaseModelSerializer):
    reason = serializers.CharField()

    class Meta:
        model = ProtocolItem
        fields = ["reason"]

    def validate(self, attrs):
        assert_protocol_item_editable(self.instance.version)
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        before = protocol_item_payload(instance)
        with transaction.atomic():
            claim_protocol_version_status(
                instance.version,
                EDITABLE_PROTOCOL_ITEM_STATUSES,
                PROTOCOL_ITEM_LOCKED_DETAIL,
            )
            removed, _per_model = instance.delete()
            if removed == 0:
                bad_request(PROTOCOL_ITEM_LOCKED_DETAIL)
            record_protocol_version_event(
                instance.version,
                actor,
                ProtocolEventAction.SUPPLEMENT_REMOVED,
                before,
                None,
                False,
                reason=validated_data["reason"],
            )
        return instance


class ProtocolVersionApproveSerializer(BaseModelSerializer):
    starts_on = serializers.DateField()
    ends_on = serializers.DateField(required=False, allow_null=True)
    approval_notes = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )

    class Meta:
        model = ProtocolVersion
        fields = ["starts_on", "ends_on", "approval_notes"]

    def validate(self, attrs):
        if self.instance.status not in APPROVABLE_PROTOCOL_VERSION_STATUSES:
            bad_request(
                "Protocol version can only be approved while it is draft or under review."
            )
        if not self.instance.items.exists():
            bad_request("Add at least one supplement before approving this version.")
        if version_has_inactive_supplement(self.instance):
            bad_request(INACTIVE_SUPPLEMENT_DETAIL)
        ends_on = attrs.get("ends_on")
        if ends_on is not None and ends_on < attrs["starts_on"]:
            raise serializers.ValidationError(
                {"ends_on": ["ends_on must be on or after starts_on."]}
            )
        if ends_on is None:
            ends_on = default_protocol_ends_on(attrs["starts_on"])
        if ends_on < timezone.localdate():
            raise serializers.ValidationError(
                {"ends_on": ["ends_on must be on or after today."]}
            )
        notes = attrs.get("approval_notes")
        if isinstance(notes, str):
            notes = notes.strip() or None
        attrs["ends_on"] = ends_on
        attrs["approval_notes"] = notes
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        before = protocol_version_window_payload(instance)
        now = timezone.localtime()
        with transaction.atomic():
            updated = (
                ProtocolVersion.objects.filter(
                    pk=instance.pk,
                    status__in=APPROVABLE_PROTOCOL_VERSION_STATUSES,
                )
                .filter(protocol_version_has_items())
                .filter(~protocol_version_has_inactive_supplement())
                .update(
                    status=ProtocolVersionStatus.APPROVED,
                    starts_on=validated_data["starts_on"],
                    ends_on=validated_data["ends_on"],
                    approval_notes=validated_data["approval_notes"],
                    approved_at=now,
                    approved_by=actor,
                    updated_at=now,
                )
            )
            if updated == 0:
                reject_failed_protocol_approve(instance)
            instance.status = ProtocolVersionStatus.APPROVED
            instance.starts_on = validated_data["starts_on"]
            instance.ends_on = validated_data["ends_on"]
            instance.approval_notes = validated_data["approval_notes"]
            instance.approved_at = now
            instance.approved_by = actor
            ProtocolEvent.objects.create(
                customer_profile=instance.protocol.customer_profile,
                protocol=instance.protocol,
                protocol_version=instance,
                actor=actor,
                action=ProtocolEventAction.APPROVED,
                before=before,
                after=protocol_version_window_payload(instance),
                client_visible=False,
            )
        return instance


PUBLISH_EVENT_ACTIONS = {
    ProtocolVersionStatus.SCHEDULED: ProtocolEventAction.SCHEDULED,
    ProtocolVersionStatus.ACTIVE: ProtocolEventAction.PUBLISHED,
}


def record_protocol_version_event(
    version,
    actor,
    action,
    before,
    after,
    client_visible,
    reason=None,
):
    ProtocolEvent.objects.create(
        customer_profile=version.protocol.customer_profile,
        protocol=version.protocol,
        protocol_version=version,
        actor=actor,
        action=action,
        reason=reason,
        before=before,
        after=after,
        client_visible=client_visible,
    )


def supersede_live_versions(protocol, actor):
    predecessors = list(
        ProtocolVersion.objects.select_related("protocol__customer_profile").filter(
            protocol=protocol,
            status__in=LIVE_PROTOCOL_VERSION_STATUSES,
        )
    )
    if not predecessors:
        return predecessors
    now = timezone.localtime()
    events = []
    for predecessor in predecessors:
        before = protocol_version_window_payload(predecessor)
        predecessor.status = ProtocolVersionStatus.SUPERSEDED
        predecessor.updated_at = now
        events.append(
            ProtocolEvent(
                customer_profile=predecessor.protocol.customer_profile,
                protocol=predecessor.protocol,
                protocol_version=predecessor,
                actor=actor,
                action=ProtocolEventAction.SUPERSEDED,
                before=before,
                after=protocol_version_window_payload(predecessor),
                client_visible=True,
            )
        )
    predecessor_pks = [predecessor.pk for predecessor in predecessors]
    ProtocolVersion.objects.filter(
        pk__in=predecessor_pks,
        status__in=LIVE_PROTOCOL_VERSION_STATUSES,
    ).update(status=ProtocolVersionStatus.SUPERSEDED, updated_at=now)
    changed_pks = set(
        ProtocolVersion.objects.filter(
            pk__in=predecessor_pks,
            status=ProtocolVersionStatus.SUPERSEDED,
            updated_at=now,
        ).values_list("pk", flat=True)
    )
    changed_events = [
        event
        for event, predecessor in zip(events, predecessors, strict=True)
        if predecessor.pk in changed_pks
    ]
    if changed_events:
        ProtocolEvent.objects.bulk_create(changed_events, batch_size=100)
    return [
        predecessor for predecessor in predecessors if predecessor.pk in changed_pks
    ]


class ProtocolVersionPublishSerializer(BaseModelSerializer):
    class Meta:
        model = ProtocolVersion
        fields = ["id"]

    def validate(self, attrs):
        version = self.instance
        if version.status != ProtocolVersionStatus.APPROVED:
            bad_request("Protocol version can only be published while it is approved.")
        if not version.items.exists():
            bad_request("Add at least one supplement before publishing this version.")
        if version_has_inactive_supplement(version):
            bad_request(INACTIVE_SUPPLEMENT_DETAIL)
        if version.starts_on is None:
            bad_request("starts_on is required before publishing this version.")
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        protocol = instance.protocol
        now = timezone.localtime()
        new_status = published_status(instance.starts_on, timezone.localdate())
        before = protocol_version_window_payload(instance)
        try:
            with transaction.atomic():
                Protocol.objects.filter(pk=protocol.pk).update(updated_at=F("updated_at"))
                current_version_pk = (
                    Protocol.objects.filter(pk=protocol.pk)
                    .values_list("current_version", flat=True)
                    .first()
                )
                previous_current = None
                if current_version_pk is not None:
                    previous_current = ProtocolVersion.objects.filter(
                        pk=current_version_pk
                    ).first()
                predecessors = supersede_live_versions(protocol, actor)
                superseded_pks = {predecessor.pk for predecessor in predecessors}
                supersedes = None
                if (
                    previous_current is not None
                    and previous_current.pk in superseded_pks
                ):
                    supersedes = previous_current
                updated = (
                    ProtocolVersion.objects.filter(
                        pk=instance.pk,
                        status=ProtocolVersionStatus.APPROVED,
                    )
                    .filter(protocol_version_has_items())
                    .filter(~protocol_version_has_inactive_supplement())
                    .update(
                        status=new_status,
                        published_at=now,
                        published_by=actor,
                        supersedes=supersedes,
                        updated_at=now,
                    )
                )
                if updated == 0:
                    reject_failed_protocol_publish(instance)
                instance.status = new_status
                instance.published_at = now
                instance.published_by = actor
                instance.supersedes = supersedes
                protocol.current_version = instance
                protocol.save(update_fields=["current_version", "updated_at"])
                ProtocolEvent.objects.filter(protocol_version=instance).update(
                    client_visible=True
                )
                record_protocol_version_event(
                    instance,
                    actor,
                    PUBLISH_EVENT_ACTIONS[new_status],
                    before,
                    protocol_version_window_payload(instance),
                    True,
                )
        except IntegrityError as error:
            if not is_protocol_one_active_violation(error):
                raise
            bad_request("This protocol already has an active version.")
        return instance


class ProtocolVersionCancelSerializer(BaseModelSerializer):
    reason = serializers.CharField()

    class Meta:
        model = ProtocolVersion
        fields = ["reason"]

    def validate(self, attrs):
        if self.instance.status not in CANCELLABLE_PROTOCOL_VERSION_STATUSES:
            bad_request("Protocol version can only be cancelled after it is approved.")
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        now = timezone.localtime()
        before = protocol_version_window_payload(instance)
        client_visible = instance.status in LIVE_PROTOCOL_VERSION_STATUSES
        reason = validated_data["reason"]
        with transaction.atomic():
            updated = ProtocolVersion.objects.filter(
                pk=instance.pk,
                status__in=CANCELLABLE_PROTOCOL_VERSION_STATUSES,
            ).update(
                status=ProtocolVersionStatus.CANCELLED,
                cancelled_at=now,
                cancelled_by=actor,
                cancellation_reason=reason,
                updated_at=now,
            )
            if updated == 0:
                bad_request(
                    "Protocol version can only be cancelled after it is approved."
                )
            instance.status = ProtocolVersionStatus.CANCELLED
            instance.cancelled_at = now
            instance.cancelled_by = actor
            instance.cancellation_reason = reason
            record_protocol_version_event(
                instance,
                actor,
                ProtocolEventAction.CANCELLED,
                before,
                protocol_version_window_payload(instance),
                client_visible,
            )
        return instance


EXTEND_STATUS_DETAIL = (
    "Protocol version can only be extended while it is scheduled or active."
)
EXTEND_OPEN_ENDED_DETAIL = "This version has no end date to extend."


def reject_failed_protocol_extend(version):
    current = (
        ProtocolVersion.objects.filter(pk=version.pk).only("status", "ends_on").first()
    )
    if current is None or current.status not in LIVE_PROTOCOL_VERSION_STATUSES:
        bad_request(EXTEND_STATUS_DETAIL)
    if current.ends_on is None:
        bad_request(EXTEND_OPEN_ENDED_DETAIL)
    raise serializers.ValidationError(
        {"ends_on": ["ends_on must be after the current end date."]}
    )


class ProtocolVersionExtendSerializer(BaseModelSerializer):
    ends_on = serializers.DateField()

    class Meta:
        model = ProtocolVersion
        fields = ["ends_on"]

    def validate(self, attrs):
        version = self.instance
        if version.status not in LIVE_PROTOCOL_VERSION_STATUSES:
            bad_request(EXTEND_STATUS_DETAIL)
        ends_on = attrs["ends_on"]
        if version.starts_on is not None and ends_on < version.starts_on:
            raise serializers.ValidationError(
                {"ends_on": ["ends_on must be on or after starts_on."]}
            )
        if ends_on < timezone.localdate():
            raise serializers.ValidationError(
                {"ends_on": ["ends_on must be on or after today."]}
            )
        if version.ends_on is None:
            bad_request(EXTEND_OPEN_ENDED_DETAIL)
        if ends_on <= version.ends_on:
            raise serializers.ValidationError(
                {"ends_on": ["ends_on must be after the current end date."]}
            )
        return attrs

    def update(self, instance, validated_data):
        actor = self.context["request"].user
        now = timezone.localtime()
        before = protocol_version_window_payload(instance)
        ends_on = validated_data["ends_on"]
        with transaction.atomic():
            updated = ProtocolVersion.objects.filter(
                pk=instance.pk,
                status__in=LIVE_PROTOCOL_VERSION_STATUSES,
                ends_on=instance.ends_on,
            ).update(ends_on=ends_on, updated_at=now)
            if updated == 0:
                reject_failed_protocol_extend(instance)
            instance.ends_on = ends_on
            record_protocol_version_event(
                instance,
                actor,
                ProtocolEventAction.EXTENDED,
                before,
                protocol_version_window_payload(instance),
                True,
            )
        return instance


class AiRecommendationItemSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    origin = serializers.CharField(read_only=True)
    decision = serializers.CharField(read_only=True)
    supplement = AiRecommendationSupplementSerializer(read_only=True)
    dosage = serializers.CharField(read_only=True, allow_null=True)
    frequency = serializers.CharField(read_only=True, allow_null=True)
    custom_frequency = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    timing = serializers.CharField(read_only=True, allow_null=True)
    duration = serializers.CharField(read_only=True, allow_null=True)
    instructions = serializers.CharField(read_only=True)
    rationale = serializers.CharField(read_only=True)
    final_dosage = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_frequency = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_custom_frequency = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_timing = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_duration = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_instructions = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )
    final_rationale = serializers.CharField(
        read_only=True,
        allow_null=True,
        allow_blank=True,
    )


class AiRecommendationItemDetailSerializer(AiRecommendationItemSerializer):
    reason = serializers.CharField(read_only=True, allow_null=True, allow_blank=True)


def cleaned_reason(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise serializers.ValidationError("This field may not be blank.")
    return cleaned


class ProtocolAiQueueSerializer(BaseSerializer):
    name = serializers.CharField(max_length=255)
    purpose = serializers.CharField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    supplement_ids = serializers.ListField(
        child=serializers.UUIDField(),
        allow_empty=False,
    )

    def validate_name(self, value):
        cleaned_name = BaseModelManager.clean_spaces(value)
        if not cleaned_name:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_name

    def validate_purpose(self, value):
        cleaned_purpose = BaseModelManager.clean_spaces(value)
        if not cleaned_purpose:
            raise serializers.ValidationError("This field may not be blank.")
        return cleaned_purpose

    def validate_notes(self, value):
        return BaseModelManager.clean_spaces(value)

    def validate_supplement_ids(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate supplement id.")
        active_ids = set(
            Supplement.objects.filter(pk__in=value, is_active=True).values_list(
                "pk",
                flat=True,
            )
        )
        if active_ids != set(value):
            raise serializers.ValidationError("Unknown or inactive supplement.")
        return value

    def create(self, validated_data):
        job = ProtocolAiJob.objects.create(
            customer_profile=self.context["customer_profile"],
            requested_by=self.context["request"].user,
            status=ProtocolAiJobStatus.PENDING,
            **validated_data,
        )
        transaction.on_commit(partial(publish_protocol_ai_wake, job.pk))
        return job


LIST_ROW_STATUS = {
    ProtocolAiJobStatus.PENDING: AiRecommendationListStatus.PROCESSING,
    ProtocolAiJobStatus.PROCESSING: AiRecommendationListStatus.PROCESSING,
    ProtocolAiJobStatus.FAILED: AiRecommendationListStatus.FAILED,
}
REVIEW_ROW_STATUS = {
    True: AiRecommendationListStatus.PENDING,
    False: AiRecommendationListStatus.COMPLETED,
}


def recommendation_list_status(job: ProtocolAiJob) -> str:
    row_status = LIST_ROW_STATUS.get(job.status)
    if row_status is not None:
        return row_status
    return REVIEW_ROW_STATUS[job.open_count > 0]


def recommendation_list_error(job: ProtocolAiJob, row_status: str) -> str | None:
    if row_status != AiRecommendationListStatus.FAILED or not job.error_detail:
        return None
    return job.error_detail


class RecommendationListCardSerializer(serializers.Serializer):
    id = serializers.UUIDField(source="recommendation_pk", allow_null=True)
    name = serializers.CharField()
    total = serializers.IntegerField()
    accepted = serializers.IntegerField()
    modified = serializers.IntegerField()
    rejected = serializers.IntegerField()


class AiRecommendationListSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    customer_profile = ProfileCardSerializer()
    recommendation = RecommendationListCardSerializer(source="*")
    model = serializers.CharField(
        source="recommendation_model",
        allow_null=True,
        allow_blank=True,
    )
    error = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    created_at = LocalIsoDateTimeField()

    def get_status(self, job: ProtocolAiJob) -> str:
        return recommendation_list_status(job)

    def get_error(self, job: ProtocolAiJob) -> str | None:
        return recommendation_list_error(job, recommendation_list_status(job))


class AiRecommendationDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    model = serializers.CharField()
    name = serializers.CharField()
    purpose = serializers.CharField()
    notes = serializers.CharField(allow_blank=True)
    protocol_version_id = serializers.UUIDField(allow_null=True)
    pending_count = serializers.IntegerField()
    accepted_count = serializers.IntegerField(source="accepted")
    modified_count = serializers.IntegerField(source="modified")
    rejected_count = serializers.IntegerField(source="rejected")
    items = AiRecommendationItemDetailSerializer(many=True)


class AiRecommendationDraftSerializer(serializers.Serializer):
    protocol_id = serializers.UUIDField(read_only=True)
    new_protocol_version_id = serializers.UUIDField(source="pk", read_only=True)
    status = serializers.CharField(read_only=True)

    def update(self, instance, validated_data):
        return create_protocol_draft(instance, self.context["request"].user)


class AiRecommendationItemDecisionSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    decision = serializers.CharField(read_only=True)


class AiRecommendationItemAcceptSerializer(AiRecommendationItemDecisionSerializer):
    def update(self, instance, validated_data):
        return accept_recommendation_item(instance)


class AiRecommendationItemRejectSerializer(AiRecommendationItemDecisionSerializer):
    reason = serializers.CharField(write_only=True)

    def validate_reason(self, value):
        return cleaned_reason(value)

    def validate(self, attrs):
        assert_item_open(self.instance)
        return attrs

    def update(self, instance, validated_data):
        return reject_recommendation_item(instance, validated_data["reason"])


class AiRecommendationItemModifySerializer(AiRecommendationItemSerializer):
    dosage = serializers.CharField()
    frequency = serializers.ChoiceField(choices=ProtocolItemFrequency.choices)
    custom_frequency = serializers.CharField(
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    timing = serializers.ChoiceField(choices=ProtocolItemTiming.choices)
    duration = serializers.CharField()
    instructions = serializers.CharField()
    reason = serializers.CharField(write_only=True)

    def validate_reason(self, value):
        return cleaned_reason(value)

    def validate(self, attrs):
        assert_item_open(self.instance)
        attrs["custom_frequency"] = clean_custom_frequency(
            attrs["frequency"],
            attrs.get("custom_frequency"),
        )
        return attrs

    def update(self, instance, validated_data):
        return apply_recommendation_item_modification(instance, validated_data)
