import hashlib

from django.core.validators import FileExtensionValidator
from django.db import IntegrityError, transaction
from rest_framework import serializers
from rest_framework.validators import UniqueValidator

from compliance.consent_journey.models import (
    UNIQ_CCH_PROFILE_VER_REQUIRED_NAME,
    ConsentForm,
    CustomerConsentHistory,
)
from compliance.consent_journey.utils.constants import (
    REQUIRED_TRUE_CONSENT_NAMES,
    ConsentDecisionType,
    ConsentName,
)
from compliance.consent_journey.utils.db import (
    build_consent_given_map_for_profiles,
    consent_rows_satisfy_latest,
    get_latest_consent_form,
    get_latest_consent_history_rows,
    is_latest_consent_given,
)
from core.utils.serializers import BaseModelSerializer, BaseSerializer

CONSENT_FORM_VERSION_EXISTS_MESSAGE = "A consent form with this version already exists."
CONSENT_FORM_NOT_LATEST_MESSAGE = "Consent form version is not the latest."
CONSENT_FORM_PDF_ONLY_MESSAGE = "Consent form must be a PDF file."
CONSENT_ACCEPT_RETRY_MESSAGE = "Consent acceptance is incomplete. Please retry."


class ConsentGivenListSerializer(serializers.ListSerializer):
    def to_representation(self, data):
        iterable = data if isinstance(data, list) else list(data)
        latest_form = get_latest_consent_form()
        self.child.context["latest_consent_form"] = latest_form
        if not iterable or latest_form is None:
            self.child.context["_consent_given_by_profile_id"] = {
                obj.pk: False for obj in iterable
            }
        else:
            profile_ids = [obj.pk for obj in iterable]
            given_map = build_consent_given_map_for_profiles(profile_ids, latest_form)
            for profile_id in profile_ids:
                given_map.setdefault(profile_id, False)
            self.child.context["_consent_given_by_profile_id"] = given_map
        return super().to_representation(iterable)


def resolve_is_latest_consent_given(serializer, instance):
    given_map = serializer.context.get("_consent_given_by_profile_id")
    if given_map is not None and instance.pk in given_map:
        return given_map[instance.pk]
    if "latest_consent_form" not in serializer.context:
        serializer.context["latest_consent_form"] = get_latest_consent_form()
    return is_latest_consent_given(
        instance, latest_form=serializer.context["latest_consent_form"]
    )


def is_consent_form_version_unique_violation(error: IntegrityError):
    error_text = str(error).lower()
    return (
        "version" in error_text
        or "consent_form_version" in error_text
        or "consent_journey_consentform_version" in error_text
    )


def is_required_consent_unique_violation(error: IntegrityError):
    return UNIQ_CCH_PROFILE_VER_REQUIRED_NAME in str(error)


def sha256_hex_of_uploaded_file(uploaded_file):
    file_hasher = hashlib.sha256()
    uploaded_file.seek(0)
    for file_chunk in uploaded_file.chunks():
        file_hasher.update(file_chunk)
    uploaded_file.seek(0)
    return file_hasher.hexdigest()


class ConsentFormUploadSerializer(BaseModelSerializer):
    consent_form = serializers.FileField(
        validators=[
            FileExtensionValidator(
                allowed_extensions=["pdf"],
                message=CONSENT_FORM_PDF_ONLY_MESSAGE,
            )
        ],
    )
    version = serializers.CharField(
        max_length=50,
        validators=[
            UniqueValidator(
                queryset=ConsentForm.objects.all(),
                message=CONSENT_FORM_VERSION_EXISTS_MESSAGE,
            )
        ],
    )

    class Meta:
        model = ConsentForm
        fields = [
            "id",
            "consent_form",
            "version",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        validated_data["consent_form_hash"] = sha256_hex_of_uploaded_file(
            validated_data["consent_form"]
        )
        try:
            return super().create(validated_data)
        except IntegrityError as error:
            if is_consent_form_version_unique_violation(error):
                raise serializers.ValidationError(
                    {"version": CONSENT_FORM_VERSION_EXISTS_MESSAGE}
                ) from error
            raise


class ConsentFormDetailSerializer(BaseModelSerializer):
    consent_form_url = serializers.FileField(source="consent_form", use_url=True)

    class Meta:
        model = ConsentForm
        fields = [
            "id",
            "version",
            "consent_form_url",
            "created_at",
        ]


class ConsentHistoryListItemSerializer(serializers.Serializer):
    """Plain Serializer so choice codes stay as stored values (Base* rewrites display)."""

    id = serializers.UUIDField()
    name = serializers.CharField(source="consent_name")
    value = serializers.BooleanField()
    consent_form_version = serializers.CharField(source="consent_form_version_id")
    decision_type = serializers.CharField()
    created_at = serializers.DateTimeField()


class ConsentHistoryDetailSerializer(serializers.Serializer):
    """Plain Serializer so choice codes stay as stored values (Base* rewrites display)."""

    id = serializers.UUIDField()
    name = serializers.CharField(source="consent_name")
    value = serializers.BooleanField()
    consent_form = ConsentFormDetailSerializer(source="consent_form_version")
    decision_type = serializers.CharField()
    created_at = serializers.DateTimeField()


def resolve_latest_consent_form(version):
    latest = get_latest_consent_form()
    if latest is None:
        raise serializers.ValidationError("No consent form has been uploaded.")
    if latest.version != version:
        raise serializers.ValidationError(CONSENT_FORM_NOT_LATEST_MESSAGE)
    return latest


def ensure_consent_form_still_latest(consent_form):
    latest = get_latest_consent_form()
    if latest is None or latest.version != consent_form.version:
        raise serializers.ValidationError(
            {"consent_form_version": CONSENT_FORM_NOT_LATEST_MESSAGE}
        )
    return latest


def resolve_marketing_consent_form_for_update(customer_profile, version):
    latest = resolve_latest_consent_form(version)
    has_marketing_consent = CustomerConsentHistory.objects.filter(
        customer_profile=customer_profile,
        consent_name=ConsentName.MARKETING_COMMUNICATIONS,
        consent_form_version_id=latest.version,
    ).exists()
    if not has_marketing_consent:
        raise serializers.ValidationError(
            "No marketing consent exists for this consent form version."
        )
    return latest


class AcceptConsentFormSerializer(BaseSerializer):
    marketing_communications = serializers.BooleanField()
    consent_form_version = serializers.CharField(max_length=50)

    def validate_consent_form_version(self, value):
        return resolve_latest_consent_form(value)

    @transaction.atomic
    def create(self, validated_data):
        customer_profile = self.context["customer_profile"]
        consent_form = ensure_consent_form_still_latest(
            validated_data["consent_form_version"]
        )
        marketing_communications = validated_data["marketing_communications"]

        existing_rows = get_latest_consent_history_rows(
            customer_profile, latest_form=consent_form
        )
        if existing_rows is not None and consent_rows_satisfy_latest(existing_rows):
            return existing_rows

        has_prior = CustomerConsentHistory.objects.filter(
            customer_profile=customer_profile
        ).exists()
        decision_type = (
            ConsentDecisionType.RE_CONFIRMATION
            if has_prior
            else ConsentDecisionType.INITIAL_CONFIRMATION
        )

        rows = [
            CustomerConsentHistory(
                customer_profile=customer_profile,
                consent_name=consent_name,
                value=True,
                consent_form_version=consent_form,
                decision_type=decision_type,
            )
            for consent_name in REQUIRED_TRUE_CONSENT_NAMES
        ]
        rows.append(
            CustomerConsentHistory(
                customer_profile=customer_profile,
                consent_name=ConsentName.MARKETING_COMMUNICATIONS,
                value=marketing_communications,
                consent_form_version=consent_form,
                decision_type=decision_type,
            )
        )
        try:
            with transaction.atomic():
                return CustomerConsentHistory.objects.bulk_create(rows)
        except IntegrityError as error:
            if not is_required_consent_unique_violation(error):
                raise
            existing_rows = get_latest_consent_history_rows(
                customer_profile, latest_form=consent_form
            )
            if existing_rows is not None and consent_rows_satisfy_latest(existing_rows):
                return existing_rows
            raise serializers.ValidationError(CONSENT_ACCEPT_RETRY_MESSAGE) from error


class UpdateMarketingConsentSerializer(BaseSerializer):
    value = serializers.BooleanField()
    consent_form_version = serializers.CharField(max_length=50)

    def validate_consent_form_version(self, value):
        return resolve_marketing_consent_form_for_update(
            self.context["customer_profile"],
            value,
        )

    def create(self, validated_data):
        customer_profile = self.context["customer_profile"]
        consent_form = ensure_consent_form_still_latest(
            validated_data["consent_form_version"]
        )
        value = validated_data["value"]
        latest_marketing = (
            CustomerConsentHistory.objects.filter(
                customer_profile=customer_profile,
                consent_name=ConsentName.MARKETING_COMMUNICATIONS,
                consent_form_version_id=consent_form.version,
            )
            .order_by("-created_at")
            .first()
        )
        if latest_marketing is not None and latest_marketing.value == value:
            return latest_marketing
        return CustomerConsentHistory.objects.create(
            customer_profile=customer_profile,
            consent_name=ConsentName.MARKETING_COMMUNICATIONS,
            value=value,
            consent_form_version=consent_form,
            decision_type=ConsentDecisionType.RE_CONFIRMATION,
        )
