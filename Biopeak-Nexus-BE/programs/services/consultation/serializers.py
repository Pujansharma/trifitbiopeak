from django.db import transaction
from rest_framework import serializers

from accounts.centers.models import Center
from accounts.centers.serializers import MinimumCenterSerializer
from accounts.users.serializers import BaseUserSerializer
from core.utils.serializers import BaseModelSerializer
from programs.services.models import CenterServiceAssignment, Service
from programs.services.serializers import BaseServiceSerializerMeta
from programs.services.utils.constants import ServiceCategory
from programs.services.utils.db import update_service_center_count


class ConsultationServiceSerializer(BaseServiceSerializerMeta, BaseModelSerializer):
    service_category = serializers.CharField(read_only=True)
    service_category_code = serializers.CharField(
        source="service_category", read_only=True,
    )
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "image",
            "is_global",
            "is_active",
            "add_centers",
            "remove_centers",
            "centers",
            "centers_count",
            "service_category",
            "service_category_code",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["centers_count"]

    def get_centers(self, instance: Service):
        assignments = instance.active_center_assignments[:5]
        return MinimumCenterSerializer(
            [assignment.center for assignment in assignments],
            many=True,
            context=self.context,
        ).data

    def validate(self, attrs: dict) -> dict:
        attrs = super().validate(attrs)
        is_global = attrs.get(
            "is_global", self.instance.is_global if self.instance else False,
        )
        if is_global:
            attrs["add_centers"] = []
            attrs["remove_centers"] = []
            return attrs

        for field in ["add_centers", "remove_centers"]:
            identifiers = {center["id"] for center in attrs.get(field) or []}
            valid_identifiers = set(
                Center.objects.filter(pk__in=identifiers).values_list("pk", flat=True)
            )
            missing_identifiers = identifiers - valid_identifiers
            if missing_identifiers:
                invalid_identifiers = ", ".join(
                    sorted(map(str, missing_identifiers))
                )
                raise serializers.ValidationError(
                    {field: f"Invalid center IDs provided: {invalid_identifiers}"}
                )
        return attrs

    def update_centers(
            self, service: Service, add_centers: list, remove_centers: list,
    ) -> None:
        assignments = CenterServiceAssignment.objects.filter(service=service)
        if service.is_global:
            assignments.delete()
        else:
            remove_identifiers = {center["id"] for center in remove_centers}
            add_identifiers = {center["id"] for center in add_centers}
            assignments.filter(center__pk__in=remove_identifiers).delete()
            assignments.filter(center__pk__in=add_identifiers).update(is_active=True)
            existing_identifiers = set(
                assignments.filter(center__pk__in=add_identifiers).values_list(
                    "center__pk", flat=True,
                )
            )
            CenterServiceAssignment.objects.bulk_create(
                [
                    CenterServiceAssignment(service=service, center_id=identifier)
                    for identifier in add_identifiers - existing_identifiers
                ]
            )
            if not assignments.filter(is_active=True).exists():
                raise serializers.ValidationError(
                    {"add_centers": "At least one center is required when all centers is off."}
                )
        update_service_center_count(service.pk)
        service.refresh_from_db()
        service.active_center_assignments = list(
            assignments.filter(is_active=True).select_related("center")
        )

    def create(self, validated_data: dict) -> Service:
        add_centers = validated_data.pop("add_centers", None) or []
        remove_centers = validated_data.pop("remove_centers", None) or []
        validated_data["service_category"] = ServiceCategory.CONSULTATION
        with transaction.atomic():
            service = super().create(validated_data)
            self.update_centers(service, add_centers, remove_centers)
        return service

    def update(self, instance: Service, validated_data: dict) -> Service:
        add_centers = validated_data.pop("add_centers", None) or []
        remove_centers = validated_data.pop("remove_centers", None) or []
        validated_data["service_category"] = ServiceCategory.CONSULTATION
        with transaction.atomic():
            instance = super().update(instance, validated_data)
            self.update_centers(instance, add_centers, remove_centers)
        return instance
