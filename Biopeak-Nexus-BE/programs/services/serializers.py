from django.db import transaction
from rest_framework import serializers

from accounts.centers.models import Center
from accounts.centers.serializers import BaseCenterSerializer, MinimumCenterSerializer
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from programs.services.models import (
    CenterServiceAssignment,
    Service,
    ServiceCareTemplate,
    ServiceDocument,
    ServiceProductAssignment,
    ResultRequestFile,
)
from programs.services.utils.constants import get_service_document_module_category
from programs.services.utils.db import (
    update_service_center_count,
    upsert_service_care_template,
)


class ResultRequestFileSerializer(BaseModelSerializer):
    class Meta:
        model = ResultRequestFile
        fields = [
            "id",
            "field_name",
            "file",
            "filename",
            "content_type",
            "is_active",
            "created_at",
            "updated_at"
        ]
        read_only_fields = fields


class ResultRequestFilesSerializer(BaseModelSerializer):
    files = serializers.SerializerMethodField()

    def get_files(self, instance):
        files = getattr(instance, "preview_files", None)
        if files is None:
            files = instance.files.all()[:3]
        return ResultRequestFileSerializer(
            files, many=True, context=self.context
        ).data


class CenterIDSerializer(BaseSerializer):
    id = serializers.UUIDField(required=True, write_only=True)


class BaseServiceSerializer(BaseModelSerializer):
    centers = serializers.SerializerMethodField(read_only=True)
    service_category_code = serializers.CharField(
        source="service_category", read_only=True
    )

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "service_category",
            "service_category_code",
            "image",
            "centers",
        ]

    def get_centers(self, instance):
        assignments = getattr(instance, "active_center_assignments", None)
        if assignments is None:
            assignments = instance.center_assignments.filter(
                is_active=True,
            ).select_related("center")[:3]
        if not assignments:
            return None
        centers = [assignment.center for assignment in assignments[:3]]
        return BaseCenterSerializer(centers, many=True, context=self.context).data


class BaseServiceDocumentModuleCategorySerializer(BaseModelSerializer):
    module_category = serializers.SerializerMethodField(read_only=True)
    module_category_code = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ServiceDocument
        fields = ["module_category", "module_category_code"]

    @classmethod
    def get_module_category(cls, instance: ServiceDocument):
        module_category = get_service_document_module_category(
            instance.result.document_type
        )
        return module_category.label

    @classmethod
    def get_module_category_code(cls, instance: ServiceDocument):
        return get_service_document_module_category(instance.result.document_type)


class MinimalServiceCenterSerializer(BaseModelSerializer):
    id = serializers.UUIDField(source="center.id", read_only=True)
    code = serializers.CharField(source="center.code", read_only=True)
    name = serializers.CharField(source="center.name", read_only=True)

    class Meta:
        model = CenterServiceAssignment
        fields = ["id", "code", "name"]


class MinimalServiceProductSerializer(BaseModelSerializer):
    id = serializers.UUIDField(source="product.id", read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)
    code = serializers.CharField(source="product.code", read_only=True)

    class Meta:
        model = ServiceProductAssignment
        fields = ["id", "name", "code"]


class BaseServiceSerializerMeta(BaseSerializer):
    add_centers = CenterIDSerializer(
        many=True, required=False, allow_null=True, allow_empty=True, write_only=True
    )
    remove_centers = CenterIDSerializer(
        many=True, required=False, allow_null=True, allow_empty=True, write_only=True
    )
    centers = serializers.SerializerMethodField(read_only=True)

    def get_centers(self, instance):
        center_assignments = getattr(instance, "center_assignments")
        assignments = center_assignments.all()[:3]
        centers = [asg.center for asg in assignments]
        return MinimumCenterSerializer(centers, many=True, context=self.context).data

    @classmethod
    def get_invalid_centers(cls, center_ids):
        _center_ids = set(
            Center.objects.filter(pk__in=center_ids).values_list("pk", flat=True)
        )
        return set(center_ids) - set(_center_ids)

    @classmethod
    def remove_all_centers(cls, service):
        CenterServiceAssignment.objects.filter(service=service).delete()

    def add_centers_action(self, service: Service, add_centers: list) -> None:
        if not add_centers:
            return
        center_ids = [i.get("id") for i in add_centers]
        missing_ids = self.get_invalid_centers(center_ids)
        if missing_ids:
            raise serializers.ValidationError(
                {
                    "add_centers": f"Invalid center IDs provided: {', '.join(map(str, missing_ids))}"
                }
            )

        assignments = [
            CenterServiceAssignment(service=service, center_id=cid, is_active=True)
            for cid in center_ids
        ]
        CenterServiceAssignment.objects.bulk_create(assignments, ignore_conflicts=True)

    def remove_centers_action(self, service: Service, remove_centers: list) -> None:
        if not remove_centers:
            return
        center_ids = [i.get("id") for i in remove_centers]
        missing_ids = self.get_invalid_centers(center_ids)
        if missing_ids:
            raise serializers.ValidationError(
                {
                    "remove_centers": f"Invalid center IDs provided: {', '.join(map(str, missing_ids))}"
                }
            )

        CenterServiceAssignment.objects.filter(
            service=service, center_id__in=center_ids
        ).delete()

    def validate_name(self, value):
        return value.strip()

    def validate(self, attrs):
        name = attrs.get("name")
        if name is None and self.instance is not None:
            name = self.instance.name
        if name:
            clash = Service.objects.filter(name__iexact=name)
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"name": ["A service with this name already exists."]}
                )
        return attrs


class ServiceCareTemplateSerializer(BaseModelSerializer):
    class Meta:
        model = ServiceCareTemplate
        fields = [
            "pre_template_name",
            "post_template_name",
        ]


class ServiceCareTemplateField(serializers.Field):
    """
    Nested care template config (read+write), keyed by service id.
    Same shape as RequiredRoleIdsField: get_attribute returns parent instance.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("allow_null", True)
        super().__init__(**kwargs)

    def get_attribute(self, instance):
        return instance

    def to_representation(self, instance):
        # Prefer select_related cache (None when no row); avoid reverse-O2O raise.
        fields_cache = instance._state.fields_cache
        if "care_template" in fields_cache:
            care = fields_cache["care_template"]
        else:
            care = ServiceCareTemplate.objects.filter(service=instance).first()
        if care is None:
            return None
        return ServiceCareTemplateSerializer(care).data

    def to_internal_value(self, data):
        if data is None:
            return None
        serializer = ServiceCareTemplateSerializer(data=data)
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data


class ServiceSerializer(BaseServiceSerializerMeta, BaseModelSerializer):
    is_active = serializers.BooleanField(default=True, required=False)
    is_locked = serializers.BooleanField(default=False, read_only=True)
    service_category_code = serializers.CharField(
        source="service_category", read_only=True
    )
    care_template = ServiceCareTemplateField()

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
        ]

    def create(self, validated_data):
        is_global = validated_data.get("is_global", False)
        add_centers = validated_data.pop("add_centers", [])
        remove_centers = validated_data.pop("remove_centers", [])
        care_data = validated_data.pop("care_template", serializers.empty)
        if not is_global and not add_centers and not remove_centers:
            raise serializers.ValidationError(
                "Center IDs must be provided when all centers is off"
            )

        with transaction.atomic():
            service = super().create(validated_data)
            if is_global:
                self.remove_all_centers(service)

            self.add_centers_action(service, add_centers)
            self.remove_centers_action(service, remove_centers)
            update_service_center_count(service.pk)
            if care_data is not serializers.empty:
                upsert_service_care_template(service, care_data)
        return service

    def update(self, instance: Service, validated_data):
        is_global = validated_data.get("is_global", instance.is_global)
        add_centers = validated_data.pop("add_centers", [])
        remove_centers = validated_data.pop("remove_centers", [])
        care_data = validated_data.pop("care_template", serializers.empty)
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if is_global:
                self.remove_all_centers(service=instance)

            self.add_centers_action(instance, add_centers)
            self.remove_centers_action(instance, remove_centers)

            if add_centers or remove_centers or is_global:
                update_service_center_count(instance.pk)
            if care_data is not serializers.empty:
                upsert_service_care_template(instance, care_data)
        return instance
