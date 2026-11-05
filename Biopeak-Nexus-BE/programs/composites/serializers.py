from uuid import UUID

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.centers.models import Center
from accounts.centers.serializers import MinimumCenterSerializer
from accounts.customers.models import CustomerCenterAssignment, CustomerProfile
from accounts.customers.serializers import CustomerProfileWithCenterSerializer
from accounts.users.serializers import BaseUserSerializer
from core.utils.serializers import BaseModelSerializer, BaseSerializer
from products.serializers import BaseProductSerializer
from programs.composites.models import (
    CompositeServicePrerequisite,
    CompositeTemplate,
    CompositeTemplateService,
)
from programs.composites.utils.constants import (
    CompositeAssessmentType,
    PrerequisiteCondition,
)
from programs.composites.utils.db import (
    create_program_service_extensions,
    update_composite_program_service_counts,
    update_composite_template_services_count,
    update_prerequisite_related_service_count,
)
from programs.composites.validators import (
    get_available_therapy_center_pairs,
    get_duplicate_therapy_service_identifiers,
    get_eligible_customer_centers,
    get_invalid_therapy_quantity_identifiers,
    get_invalid_therapy_service_identifiers,
    get_therapy_template_service_identifiers,
)
from programs.models import CompositeProgram, Program, ProgramService
from programs.serializers import AssignedProgramServiceSerializer
from programs.services.models import CenterServiceAssignment, Service, ServiceDocument
from programs.services.serializers import BaseServiceSerializer, CenterIDSerializer
from programs.services.utils.constants import ServiceCategory
from programs.utils.audit import create_program_audit_log
from programs.utils.constants import ProgramType, ServiceAssignment
from programs.utils.db import (
    cancel_all_program_services,
    update_program_redeemable_centers_count,
    update_program_services_count,
)
from programs.utils.helper import generate_program_unique_id


class CompositeTemplateServiceReferenceSerializer(BaseSerializer):
    id = serializers.UUIDField(required=True, write_only=True)
    quantity = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, write_only=True,
    )


class CompositeAddOnServiceReferenceSerializer(BaseSerializer):
    id = serializers.UUIDField(required=True, write_only=True)
    sessions_count = serializers.IntegerField(
        min_value=1, required=False, allow_null=True, write_only=True,
    )
    centers = CenterIDSerializer(
        many=True, required=False, allow_empty=True, write_only=True,
    )


class CompositeTherapyServiceSelectionSerializer(BaseSerializer):
    id = serializers.UUIDField()
    centers = CenterIDSerializer(many=True, required=False, allow_empty=True)


class CompositePrerequisiteServiceReferenceSerializer(BaseSerializer):
    id = serializers.UUIDField(required=True)


class CompositePrerequisiteServiceSerializer(BaseModelSerializer):
    name = serializers.CharField(source="service.name", read_only=True)
    service_category = serializers.CharField(
        source="service.get_service_category_display",
        read_only=True,
    )
    service_category_code = serializers.CharField(
        source="service.service_category",
        read_only=True,
    )

    class Meta:
        model = CompositeTemplateService
        fields = [
            "id",
            "name",
            "service_category",
            "service_category_code",
        ]
        read_only_fields = fields


class CompositeAvailablePrerequisiteServiceSerializer(
    CompositePrerequisiteServiceSerializer
):
    is_exists = serializers.BooleanField(default=False, read_only=True)

    class Meta:
        model = CompositeTemplateService
        fields = [
            "id",
            "name",
            "service_category",
            "service_category_code",
            "is_exists",
        ]
        read_only_fields = fields


class CompositeServicePrerequisitePreviewSerializer(BaseModelSerializer):
    related_services = serializers.SerializerMethodField(read_only=True)
    condition = serializers.ChoiceField(
        choices=PrerequisiteCondition,
        required=False,
    )
    condition_code = serializers.CharField(
        source="condition",
        read_only=True,
    )
    related_services_count = serializers.IntegerField(default=0, read_only=True)

    class Meta:
        model = CompositeServicePrerequisite
        fields = [
            "related_services_count",
            "related_services",
            "condition",
            "condition_code",
        ]

    def get_related_services(self, instance: CompositeServicePrerequisite):
        related_services = getattr(instance, "related_service_preview", [])[:5]
        return CompositePrerequisiteServiceSerializer(
            related_services, many=True, context=self.context,
        ).data


class CompositeProgramCenterSerializer(BaseSerializer):
    id = serializers.UUIDField(required=True, write_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class BaseCompositeTemplateSerializer(BaseModelSerializer):
    class Meta:
        model = CompositeTemplate
        fields = ["id", "code", "name", "is_active"]
        read_only_fields = fields


class CompositeTemplateServiceSerializer(BaseModelSerializer):
    service = BaseServiceSerializer(read_only=True)
    name = serializers.CharField(source="service.name", read_only=True)
    is_global = serializers.BooleanField(source="service.is_global", read_only=True)
    service_category = serializers.SerializerMethodField(read_only=True)
    service_category_code = serializers.CharField(
        source="service.service_category", read_only=True
    )
    image = serializers.FileField(
        source="service.image", read_only=True, allow_null=True
    )
    is_active = serializers.BooleanField(source="service.is_active", read_only=True)
    is_locked = serializers.BooleanField(read_only=True, default=False)
    centers = serializers.SerializerMethodField(read_only=True)
    centers_count = serializers.IntegerField(
        source="service.centers_count", read_only=True
    )
    # redeemable_centers = serializers.SerializerMethodField(read_only=True)
    redeemable_centers_count = serializers.SerializerMethodField(read_only=True)
    products = serializers.SerializerMethodField(read_only=True)
    products_count = serializers.IntegerField(
        source='service.products_count', default=0, read_only=True
    )
    created_at = serializers.DateTimeField(source="service.created_at", read_only=True)
    updated_at = serializers.DateTimeField(source="service.updated_at", read_only=True)
    created_by = BaseUserSerializer(source="service.created_by", read_only=True)
    prerequisite = CompositeServicePrerequisitePreviewSerializer(
        read_only=True,
        allow_null=True,
    )

    class Meta:
        model = CompositeTemplateService
        fields = [
            "id",
            "name",
            "service",
            "quantity",
            "is_global",
            "service_category",
            "service_category_code",
            "image",
            "is_active",
            "is_locked",
            "centers",
            "centers_count",
            # "redeemable_centers",
            "redeemable_centers_count",
            "products",
            "products_count",
            "created_at",
            "updated_at",
            "created_by",
            "prerequisite",
        ]
        read_only_fields = fields

    @staticmethod
    def _get_center_preview(instance: CompositeTemplateService):
        center_assignments = instance.service.center_assignments.all()[:5]
        return [
            center_assignment.center for center_assignment in center_assignments
        ]

    @classmethod
    def get_service_category(
            cls, instance: CompositeTemplateService,
    ):
        return instance.service.get_service_category_display()

    def get_centers(self, instance):
        centers = []
        if instance.service.service_category == ServiceCategory.THERAPY:
            assignments = getattr(instance.service, "selectable_center_assignments", [])
            for assignment in assignments:
                centers.append(assignment.center)
        return MinimumCenterSerializer(
            centers,
            many=True,
            context=self.context,
        ).data

    def get_redeemable_centers(self, instance):
        if instance.service.service_category not in [
            ServiceCategory.THERAPY
        ]:
            return []
        return self.get_centers(instance)

    @classmethod
    def get_redeemable_centers_count(
            cls, instance: CompositeTemplateService,
    ):
        if instance.service.service_category not in [
            ServiceCategory.THERAPY
        ]:
            return 0
        return instance.service.centers_count

    def get_products(self, instance):
        if instance.service.service_category != ServiceCategory.ASSESSMENT:
            return []
        product_assignments = instance.service.product_assignments.all()[:5]
        products = [
            product_assignment.product for product_assignment in product_assignments
        ]
        return BaseProductSerializer(
            products,
            many=True,
            context=self.context,
        ).data


class CompositeServicePrerequisiteSerializer(
    CompositeServicePrerequisitePreviewSerializer
):
    add_related_services = CompositePrerequisiteServiceReferenceSerializer(
        many=True,
        required=True,
        allow_empty=True,
        write_only=True,
    )
    remove_related_services = CompositePrerequisiteServiceReferenceSerializer(
        many=True,
        required=True,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = CompositeServicePrerequisite
        fields = [
            "add_related_services",
            "remove_related_services",
            "related_services_count",
            "related_services",
            "condition",
            "condition_code",
        ]

    @classmethod
    def _get_invalid_template_service_ids(
            cls, related_services, composite_template
    ):
        _ids = [i['id'] for i in related_services]
        qs = CompositeTemplateService.objects.filter(
            pk__in=_ids,
            composite_template=composite_template,
        ).values_list("pk", flat=True)
        invalid_ids = set(_ids) - set(qs)
        return invalid_ids

    def _perform_add_related_services_action(
            self,
            add_related_service_data,
            composite_template,
            prerequisite
    ):
        if not add_related_service_data:
            return
        _invalid_add_service_ids = self._get_invalid_template_service_ids(
            add_related_service_data, composite_template
        )
        if _invalid_add_service_ids:
            raise serializers.ValidationError({
                "add_related_services": (
                    "Invalid composite template service IDs provided: "
                    f"{", ".join(map(str, _invalid_add_service_ids))}"
                )
            })
        prerequisite.related_services.add(
            *[i['id'] for i in add_related_service_data]
        )

    def _perform_remove_related_services_action(
            self,
            remove_related_service_data,
            composite_template,
            prerequisite

    ):
        if not remove_related_service_data:
            return
        _invalid_remove_service_ids = self._get_invalid_template_service_ids(
            remove_related_service_data, composite_template
        )
        if _invalid_remove_service_ids:
            raise serializers.ValidationError({
                "remove_related_services": (
                    "Invalid composite template service IDs provided: "
                    f"{", ".join(map(str, _invalid_remove_service_ids))}"
                )
            })
        prerequisite.related_services.remove(
            *[i['id'] for i in remove_related_service_data]
        )

    def create(self, validated_data: dict) -> CompositeServicePrerequisite:
        template_service = validated_data.pop("template_service", None)
        created_by = validated_data.get('created_by')
        add_related_service_data = validated_data.pop("add_related_services", None) or []
        remove_related_service_data = validated_data.pop("remove_related_services", None) or []
        condition = validated_data.get("condition", PrerequisiteCondition.REQUIRE_ANY)

        with transaction.atomic():
            prerequisite, _ = CompositeServicePrerequisite.objects.update_or_create(
                template_service=template_service,
                defaults={
                    "condition": condition,
                    "created_by": created_by,
                },
            )
            if remove_related_service_data:
                self._perform_remove_related_services_action(
                    remove_related_service_data,
                    template_service.composite_template,
                    prerequisite
                )
            if add_related_service_data:
                self._perform_add_related_services_action(
                    add_related_service_data,
                    template_service.composite_template,
                    prerequisite
                )
            update_prerequisite_related_service_count(
                prerequisite.template_service.pk
            )
            prerequisite.refresh_from_db(fields=["related_services_count"])
            prerequisite.related_service_preview = list(
                prerequisite.related_services.select_related("service")[:5]
            )

        return prerequisite

    def update(
            self,
            instance: CompositeServicePrerequisite,
            validated_data: dict,
    ) -> CompositeServicePrerequisite:
        add_related_service_data = validated_data.pop("add_related_services", None) or []
        remove_related_service_data = validated_data.pop("remove_related_services", None) or []

        with transaction.atomic():
            instance = super().update(instance, validated_data)
            if remove_related_service_data:
                self._perform_remove_related_services_action(
                    remove_related_service_data,
                    instance.template_service.composite_template,
                    instance
                )

            if add_related_service_data:
                self._perform_add_related_services_action(
                    add_related_service_data,
                    instance.template_service.composite_template,
                    instance
                )

            update_prerequisite_related_service_count(
                instance.template_service.pk
            )
            instance.refresh_from_db(fields=["related_services_count"])
            instance.related_service_preview = list(
                instance.related_services.select_related("service")[:5]
            )

        return instance


class CompositeTemplateSerializer(BaseModelSerializer):
    add_services = CompositeTemplateServiceReferenceSerializer(
        many=True,
        required=False,
        allow_empty=False,
        write_only=True,
    )
    created_by = BaseUserSerializer(read_only=True)
    code = serializers.CharField(required=True)

    class Meta:
        model = CompositeTemplate
        fields = [
            "id",
            "code",
            "name",
            "description",
            "add_services",
            "assessment_services_count",
            "therapy_services_count",
            "consultation_services_count",
            "services_count",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "services_count",
            "created_at",
            "updated_at",
            "created_by",
        ]

    def create(self, validated_data: dict):
        code = validated_data.get('code', None)
        if not code:
            raise serializers.ValidationError({'code': 'This field is required'})

        existing_code_template = CompositeTemplate.objects.filter(
            code__iexact=code
        ).first()

        if existing_code_template:
            raise serializers.ValidationError({
                'code': f'This code is already in use by: {existing_code_template.name}'
            })

        add_services = validated_data.pop("add_services", [])
        if not add_services:
            raise serializers.ValidationError({
                "add_services": "At least one service is required."
            })

        service_identifiers = set([
            service_data["id"] for service_data in add_services
        ])

        services = Service.objects.filter(
            pk__in=service_identifiers, is_active=True,
        )
        services_by_primary_key = {service.pk: service for service in services}
        invalid_service_identifiers = set(service_identifiers) - set(
            services_by_primary_key
        )
        if invalid_service_identifiers:
            invalid_identifiers = ", ".join(
                str(service_identifier)
                for service_identifier in sorted(
                    invalid_service_identifiers,
                    key=str,
                )
            )
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "Invalid or inactive service IDs provided: "
                        f"{invalid_identifiers}"
                    )
                }
            )

        service_quantities = []
        for service_data in add_services:
            service_quantities.append(
                (services_by_primary_key[service_data["id"]], service_data.get("quantity"))
            )
        invalid_quantity_identifiers = get_invalid_therapy_quantity_identifiers(
            service_quantities,
        )
        if invalid_quantity_identifiers:
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "A positive quantity is required for therapy services: "
                        f"{', '.join(sorted(invalid_quantity_identifiers))}."
                    )
                }
            )
        invalid_quantity_positions = [
            position
            for position, service_data in enumerate(add_services, start=1)
            if (
                    services_by_primary_key[service_data["id"]].service_category
                    == ServiceCategory.CONSULTATION
                    and service_data.get("quantity") is not None
            )
        ]
        if invalid_quantity_positions:
            positions = ", ".join(map(str, invalid_quantity_positions))
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "Quantity is not supported for consultation service entries. "
                        f"Remove it from positions: {positions}."
                    )
                }
            )

        created_by = validated_data.get("created_by")
        quantity_by_service = {
            service_data["id"]: service_data.get('quantity', None)
            for service_data in add_services
        }

        with transaction.atomic():
            composite_template = super().create(validated_data)
            CompositeTemplateService.objects.bulk_create(
                [
                    CompositeTemplateService(
                        composite_template=composite_template,
                        service=services_by_primary_key[service_identifier],
                        quantity=quantity_by_service[service_identifier],
                        created_by=created_by,
                    )
                    for service_identifier in service_identifiers
                ]
            )
            update_composite_template_services_count(composite_template.pk)
            composite_template.refresh_from_db(
                fields=[
                    "services_count",
                    "assessment_services_count",
                    "therapy_services_count",
                    "consultation_services_count",
                ]
            )
        return composite_template

    def update(
            self, instance: CompositeTemplate, validated_data: dict,
    ) -> CompositeTemplate:
        validated_data.pop('services', None)
        validated_data.pop('add_services', None)

        code = validated_data.get("code")
        if code:
            existing_code_template = (
                CompositeTemplate.objects.filter(code__iexact=code)
                .exclude(pk=instance.pk)
                .first()
            )
            if existing_code_template:
                raise serializers.ValidationError({
                    "code": f"This code is already in use by {existing_code_template.name}"
                })
        return super().update(instance, validated_data)

    def get_services(self, instance):
        template_services = getattr(instance, "service_preview", None)
        if not template_services:
            return None
        return CompositeTemplateServiceSerializer(
            template_services[:5],
            many=True,
            context=self.context,
        ).data


class CompositeAssignedProgramServiceSerializer(AssignedProgramServiceSerializer):
    def get_centers(self, instance: ProgramService):
        therapy_service = getattr(instance, "therapy_service", None)
        return MinimumCenterSerializer(
            getattr(therapy_service, "redeemable_center_preview", [])[:5], many=True,
            context=self.context,
        ).data


class CompositeProgramServiceSerializer(BaseModelSerializer):
    service = serializers.SerializerMethodField()
    redeemable_centers = serializers.SerializerMethodField(read_only=True)
    service_assignment_type = serializers.SerializerMethodField(read_only=True)
    service_assignment_type_code = serializers.CharField(
        source="assignment_type",
        read_only=True,
    )
    can_redeem = serializers.BooleanField(default=True, read_only=True)
    sessions_count = serializers.IntegerField(
        source="therapy_service.sessions_count", read_only=True, default=None,
    )
    sessions_used = serializers.IntegerField(
        source="therapy_service.sessions_used", read_only=True, default=None,
    )
    sessions_cancelled = serializers.IntegerField(
        source="therapy_service.sessions_cancelled", read_only=True, default=None,
    )
    redeem_code = serializers.SerializerMethodField(read_only=True)
    cancelled_by = BaseUserSerializer(read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ProgramService
        fields = [
            "id",
            "service",
            "service_assignment_type",
            "service_assignment_type_code",
            "redeemable_centers",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeem_code",
            "can_redeem",

            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "fetch_count",
            "fetch_results_count",
            "fetch_documents_count",
            "fetch_pending_count",

            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
            "created_date",
            "created_by",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def get_service(self, instance: ProgramService):
        if instance.service.service_category == ServiceCategory.THERAPY:
            return CompositeAssignedProgramServiceSerializer(
                instance, context=self.context,
            ).data
        return BaseServiceSerializer(instance.service, context=self.context).data

    @classmethod
    def get_service_assignment_type(
            cls,
            instance: ProgramService,
    ):
        _display = getattr(instance, 'get_assignment_type_display', lambda: None | str)
        return _display()

    def get_redeem_code(self, instance: ProgramService):
        therapy_program_service = getattr(instance, "therapy_service", None)
        return getattr(therapy_program_service, "redeem_code", None)

    def get_redeemable_centers(self, instance: ProgramService):
        therapy_service = getattr(instance, "therapy_service", None)
        return MinimumCenterSerializer(
            getattr(therapy_service, "redeemable_center_preview", [])[:5], many=True,
            context=self.context,
        ).data


class CompositeProgramValidationMixin:
    def _validate_composite_program_metadata(self, program_data: dict):
        is_complimentary = program_data.get("is_complimentary", True)
        is_credit = program_data.get("is_credit", False)
        if is_complimentary and is_credit:
            raise serializers.ValidationError(
                {"is_credit": "A program cannot be both complimentary and credit."}
            )
        if is_credit and program_data.get("credit_received") is None:
            raise serializers.ValidationError(
                {"credit_received": "Credit amount is required when program is credit."}
            )
        if not is_complimentary and program_data.get("price") is None:
            raise serializers.ValidationError(
                {"price": "Price is required when program is not complimentary."}
            )

    def _validate_composite_therapy_centers(
            self,
            therapy_services: list[dict],
            template_services: list[CompositeTemplateService],
            allowed_centers: dict[UUID, Center],
            customer_profile: CustomerProfile,
            is_global: bool,
    ):
        """Validate returned selections without inheriting parent therapy centers."""
        therapy_identifiers = get_therapy_template_service_identifiers(template_services)
        if not allowed_centers and (not is_global or not therapy_identifiers):
            raise serializers.ValidationError(
                {"redeemable_centers": "Select redemption centers."}
            )

        invalid_identifiers = get_invalid_therapy_service_identifiers(
            therapy_services, therapy_identifiers,
        )
        duplicate_identifiers = get_duplicate_therapy_service_identifiers(therapy_services)
        errors = {}
        for service_identifier in invalid_identifiers:
            errors[str(service_identifier)] = {
                "id": ["Select only active therapy services from this template."]
            }
        for service_identifier in duplicate_identifiers:
            errors[str(service_identifier)] = {
                "id": ["Duplicate therapy service selections are not allowed."]
            }
        if errors:
            raise serializers.ValidationError({"therapy_services": errors})

        selections_by_service = {}
        selected_center_identifiers = set()
        for selection in therapy_services:
            center_identifiers = set()
            for center_selection in selection.get("centers", []):
                center_identifiers.add(center_selection["id"])
            selections_by_service[selection["id"]] = center_identifiers
            selected_center_identifiers.update(center_identifiers)

        if is_global:
            allowed_centers = {}
            for center in get_eligible_customer_centers(
                    selected_center_identifiers, customer_profile,
            ):
                allowed_centers[center.pk] = center

        available_pairs = get_available_therapy_center_pairs(
            therapy_identifiers, selected_center_identifiers,
        )
        centers_by_service = {}
        for service_identifier, center_identifiers in selections_by_service.items():
            center_errors = []
            if center_identifiers - allowed_centers.keys():
                center_errors.append(
                    "Centers must be active customer centers within the program's redemption scope."
                )
            for center_identifier in center_identifiers:
                if (service_identifier, center_identifier) not in available_pairs:
                    center_errors.append(
                        f"This service is not available at center {center_identifier}."
                    )
            if center_errors:
                errors[str(service_identifier)] = {"centers": center_errors}
                continue
            centers_by_service[service_identifier] = []
            for center_identifier in center_identifiers:
                centers_by_service[service_identifier].append(
                    allowed_centers[center_identifier]
                )
        if errors:
            raise serializers.ValidationError({"therapy_services": errors})
        return centers_by_service


class CompositeProgramSerializer(CompositeProgramValidationMixin, BaseModelSerializer):
    therapy_redemption_is_global = serializers.BooleanField(required=False)
    therapy_services = CompositeTherapyServiceSelectionSerializer(
        many=True, required=False, write_only=True,
    )
    id = serializers.UUIDField(source="pk", read_only=True)
    uid = serializers.CharField(source="program.uid", read_only=True)
    name = serializers.CharField(
        max_length=200,
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    assessment_type = serializers.ChoiceField(
        choices=CompositeAssessmentType,
        required=False,
        allow_null=True,
    )
    assessment_type_code = serializers.CharField(
        source="assessment_type",
        read_only=True,
        allow_null=True,
    )
    profile = CustomerProfileWithCenterSerializer(
        source="program.customer_profile",
        read_only=True,
    )
    profile_id = serializers.UUIDField(write_only=True, required=True)
    center = MinimumCenterSerializer(source="program.center", read_only=True)
    composite_template = BaseCompositeTemplateSerializer(read_only=True)
    composite_template_id = serializers.UUIDField(write_only=True, required=True)
    program_type = serializers.ChoiceField(
        source="program.program_type",
        choices=ProgramType,
        read_only=True,
    )
    notes = serializers.CharField(
        source="program.notes",
        required=False,
        allow_null=True,
        allow_blank=True,
    )
    expires_at = serializers.DateField(
        source="program.expires_at", required=False, allow_null=True,
    )
    is_complimentary = serializers.BooleanField(
        source="program.is_complimentary",
        default=True,
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
    redeemable_centers = CompositeProgramCenterSerializer(
        source="program.redeemable_centers",
        many=True,
        required=False,
        allow_empty=True,
    )
    services_count = serializers.IntegerField(
        source="program.services_count",
        read_only=True,
    )
    add_ons_count = serializers.IntegerField(read_only=True)
    assessment_services_count = serializers.IntegerField(read_only=True)
    therapy_services_count = serializers.IntegerField(read_only=True)
    consultation_services_count = serializers.IntegerField(read_only=True)
    consultation_documents_count = serializers.IntegerField(read_only=True)
    consultation_files_count = serializers.IntegerField(read_only=True)
    results_count = serializers.IntegerField(read_only=True)
    documents_count = serializers.IntegerField(read_only=True)
    reports_count = serializers.IntegerField(read_only=True)
    raw_data_count = serializers.IntegerField(read_only=True)
    redeemable_centers_count = serializers.IntegerField(
        source="program.redeemable_centers_count",
        read_only=True,
    )
    cancellation_reason = serializers.CharField(
        source="program.cancellation_reason",
        read_only=True,
    )
    cancelled_by = BaseUserSerializer(
        source="program.cancelled_by",
        read_only=True,
    )
    cancelled_at = serializers.DateTimeField(
        source="program.cancelled_at",
        read_only=True,
    )
    cancelled_date = serializers.DateField(
        source="program.cancelled_date",
        read_only=True,
    )
    created_date = serializers.DateField(
        source="program.created_date",
        required=False,
    )
    is_active = serializers.BooleanField(source="program.is_active", read_only=True)
    created_at = serializers.DateTimeField(source="program.created_at", read_only=True)
    updated_at = serializers.DateTimeField(source="program.updated_at", read_only=True)
    created_by = BaseUserSerializer(source="program.created_by", read_only=True)

    class Meta:
        model = CompositeProgram
        fields = [
            "id",
            "uid",
            "name",
            "assessment_type",
            "assessment_type_code",
            "profile",
            "profile_id",
            "center",
            "composite_template",
            "composite_template_id",
            "therapy_services",
            "program_type",
            "notes",
            "expires_at",
            "is_complimentary",
            "is_credit",
            "credit_received",
            "price",
            "redeemable_centers",
            "therapy_redemption_is_global",
            "redeemable_centers_count",
            "services_count",
            "add_ons_count",
            "assessment_services_count",
            "therapy_services_count",
            "consultation_services_count",
            "consultation_documents_count",
            "consultation_files_count",
            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
            "created_date",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "services_count",
            "redeemable_centers_count",
            "created_at",
            "updated_at",
            "created_by",
        ]

    def create(self, validated_data: dict):
        if validated_data.get("name") == "":
            validated_data["name"] = None
        center = validated_data.pop("center")
        therapy_services = validated_data.pop("therapy_services", [])
        created_by = validated_data.pop("created_by")
        profile_identifier = validated_data.pop("profile_id")
        composite_template_identifier = validated_data.pop(
            "composite_template_id"
        )
        program_data = validated_data.pop("program", {})
        redeemable_center_data = program_data.pop("redeemable_centers", [])
        if validated_data.get("therapy_redemption_is_global"):
            redeemable_center_data = []
        expires_at = program_data.get("expires_at")
        if expires_at and expires_at < timezone.localdate():
            raise serializers.ValidationError(
                {"expires_at": "Expiry date cannot be earlier than today's date."}
            )
        self._validate_composite_program_metadata(program_data)

        customer_profile = (
            CustomerProfile.objects.filter(
                pk=profile_identifier,
                is_active=True,
                center_assignments__center=center,
                center_assignments__is_active=True,
            )
            .distinct()
            .first()
        )
        if not customer_profile:
            raise serializers.ValidationError(
                {"profile_id": "Customer profile is not assigned to this center."}
            )

        center_identifiers = set([
            center_data["id"] for center_data in redeemable_center_data
        ])

        center_assignments = CustomerCenterAssignment.objects.filter(
            customer_profile=customer_profile,
            center__pk__in=center_identifiers,
            center__is_active=True,
            is_active=True,
        ).select_related("center")
        centers_by_primary_key = {
            center_assignment.center.pk: center_assignment.center
            for center_assignment in center_assignments
        }
        invalid_center_identifiers = set(center_identifiers) - set(
            centers_by_primary_key
        )
        if invalid_center_identifiers:
            invalid_identifiers = ", ".join(
                str(center_identifier)
                for center_identifier in sorted(
                    invalid_center_identifiers,
                    key=str,
                )
            )
            raise serializers.ValidationError(
                {
                    "redeemable_centers": (
                        "Centers are not assigned to this customer profile: "
                        f"{invalid_identifiers}"
                    )
                }
            )
        redeemable_centers = [
            centers_by_primary_key[center_identifier]
            for center_identifier in center_identifiers
        ]

        composite_template = CompositeTemplate.objects.filter(
            pk=composite_template_identifier,
            is_active=True,
        ).first()
        if not composite_template:
            raise serializers.ValidationError(
                {"composite_template_id": "Invalid or inactive composite template."}
            )

        template_services = list(
            CompositeTemplateService.objects.filter(
                composite_template=composite_template,
                is_active=True,
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
        has_assessment_service = any(
            template_service.service.service_category
            == ServiceCategory.ASSESSMENT
            for template_service in template_services
        )
        if has_assessment_service and not validated_data.get("assessment_type"):
            raise serializers.ValidationError(
                {
                    "assessment_type": (
                        "Assessment type is required when the composite template "
                        "contains an assessment service."
                    )
                }
            )

        is_global = validated_data.get(
            "therapy_redemption_is_global", not centers_by_primary_key,
        )
        centers_by_service = self._validate_composite_therapy_centers(
            therapy_services,
            template_services,
            centers_by_primary_key,
            customer_profile,
            is_global,
        )
        validated_data["therapy_redemption_is_global"] = is_global
        service_centers = []
        for template_service in template_services:
            service_centers.append(centers_by_service.get(template_service.service.pk, []))

        with transaction.atomic():
            program_uid = generate_program_unique_id()
            program = Program.objects.create(
                **program_data,
                uid=program_uid,
                program_type=ProgramType.COMPOSITE,
                customer_profile=customer_profile,
                center=center,
                created_by=created_by,
            )
            program.redeemable_centers.add(*redeemable_centers)
            validated_data["program"] = program
            validated_data["composite_template"] = composite_template
            validated_data["template_description"] = composite_template.description
            composite_program = super().create(validated_data)
            service_quantities = [
                template_service.quantity
                for template_service in template_services
            ]
            program_services = [
                ProgramService(
                    program=program,
                    service=template_service.service,
                    created_by=created_by,
                )
                for template_service in template_services
            ]
            ProgramService.objects.bulk_create(program_services)
            create_program_service_extensions(
                program_services,
                service_quantities,
                service_centers,
            )
            update_program_services_count(program.pk)
            update_composite_program_service_counts(program.pk)
            update_program_redeemable_centers_count(program.pk)
            composite_program.refresh_from_db(
                fields=[
                    "add_ons_count",
                    "assessment_services_count",
                    "therapy_services_count",
                    "consultation_services_count",
                ]
            )
            program.refresh_from_db(
                fields=["services_count", "redeemable_centers_count"]
            )
        return composite_program


class CompositeProgramDetailSerializer(CompositeProgramSerializer):
    is_credit = serializers.BooleanField(source="program.is_credit", required=False)
    is_complimentary = serializers.BooleanField(
        source="program.is_complimentary", required=False,
    )
    credit_received = serializers.DecimalField(
        source="program.credit_received", max_digits=10, decimal_places=2,
        read_only=True, allow_null=True,
    )
    profile_id = serializers.UUIDField(write_only=True, required=False)
    composite_template_id = serializers.UUIDField(write_only=True, required=False)
    expires_at = serializers.DateField(
        source="program.expires_at",
        required=False,
        allow_null=True,
    )
    redeemable_centers = MinimumCenterSerializer(
        source="program.redeemable_centers",
        many=True,
        read_only=True,
    )
    add_redeemable_centers = CenterIDSerializer(
        many=True, required=False, write_only=True, allow_empty=True,
    )
    created_date = serializers.DateField(
        source="program.created_date",
        read_only=True,
    )

    class Meta:
        model = CompositeProgram
        fields = [
            "id",
            "uid",
            "name",
            "assessment_type",
            "assessment_type_code",
            "profile",
            "profile_id",
            "center",
            "composite_template",
            "composite_template_id",
            "therapy_services",
            "program_type",
            "notes",
            "expires_at",
            "is_complimentary",
            "is_credit",
            "credit_received",
            "price",
            "redeemable_centers",
            "add_redeemable_centers",
            "therapy_redemption_is_global",
            "redeemable_centers_count",
            "services_count",
            "add_ons_count",
            "assessment_services_count",
            "therapy_services_count",
            "consultation_services_count",
            "consultation_documents_count",
            "consultation_files_count",
            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
            "created_date",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
        ]
        read_only_fields = [
            "id",
            "services_count",
            "redeemable_centers",
            "redeemable_centers_count",
            "created_at",
            "updated_at",
            "created_by",
        ]

    def update(
            self,
            instance: CompositeProgram,
            validated_data: dict,
    ):
        created_by = validated_data.pop("created_by")
        validated_data.pop("therapy_services", None)
        validated_data.pop("assessment_type", None)
        validated_data.pop("assessment_type_code", None)
        validated_data.pop("profile_id", None)
        validated_data.pop("composite_template_id", None)
        validated_data.pop("redeemable_centers", None)
        validated_data.pop("created_date", None)

        program_data = validated_data.pop("program", {})
        center_selections = validated_data.pop("add_redeemable_centers", [])
        center_identifiers = set()
        for selection in center_selections:
            center_identifiers.add(selection["id"])
        eligible_identifiers = set(
            get_eligible_customer_centers(
                center_identifiers, instance.program.customer_profile,
            ).values_list("pk", flat=True)
        )
        if center_identifiers - eligible_identifiers:
            raise serializers.ValidationError(
                {"add_redeemable_centers": "Select active customer centers."}
            )
        is_global = validated_data.pop("therapy_redemption_is_global", None)
        if is_global is not None:
            if not instance.program.program_services.filter(
                    service__service_category=ServiceCategory.THERAPY,
            ).exists():
                raise serializers.ValidationError("Therapy coverage requires a therapy service.")
        expires_at = program_data.get("expires_at")
        if expires_at and expires_at < timezone.localdate():
            raise serializers.ValidationError(
                {"expires_at": "Expiry date cannot be earlier than today's date."}
            )
        is_complimentary = program_data.get(
            "is_complimentary", instance.program.is_complimentary,
        )
        is_credit = program_data.get("is_credit", instance.program.is_credit)
        if is_complimentary and is_credit:
            raise serializers.ValidationError(
                {"is_credit": "A program cannot be both complimentary and credit."}
            )
        price = program_data.get("price", instance.program.price)
        if not is_complimentary and price is None:
            raise serializers.ValidationError(
                {"price": "Price is required when program is not complimentary."}
            )
        with transaction.atomic():
            for field, value in program_data.items():
                create_program_audit_log(
                    instance.program, field, getattr(instance.program, field),
                    value, created_by,
                )
                setattr(instance.program, field, value)
            # Write the parent before reading centers, matching therapy's addition flow.
            instance.program.save(update_fields=[*program_data.keys(), "updated_at"])
            existing_center_identifiers = set(
                instance.program.redeemable_centers.values_list("pk", flat=True)
            )
            all_center_identifiers = existing_center_identifiers | center_identifiers
            if is_global is False and not all_center_identifiers:
                raise serializers.ValidationError(
                    {"add_redeemable_centers": "Select redemption centers."}
                )
            composite_update_fields = []
            if "name" in validated_data:
                instance.name = validated_data["name"]
                composite_update_fields.append("name")
            if is_global is not None:
                instance.therapy_redemption_is_global = is_global
                composite_update_fields.append("therapy_redemption_is_global")
            if composite_update_fields:
                instance.save(update_fields=[*composite_update_fields, "updated_at"])
            if center_identifiers:
                instance.program.redeemable_centers.add(*center_identifiers)
                create_program_audit_log(
                    instance.program,
                    "redeemable_centers",
                    sorted(map(str, existing_center_identifiers)),
                    sorted(map(str, all_center_identifiers)),
                    created_by,
                )
                update_program_redeemable_centers_count(instance.program.pk)
                instance.program.refresh_from_db(fields=["redeemable_centers_count"])
        return instance

    def create(self, validated_data: dict) -> CompositeProgram:
        raise serializers.ValidationError("Create not allowed.")


class CompositeProgramCancelSerializer(BaseModelSerializer):
    cancellation_reason = serializers.CharField(
        source="program.cancellation_reason",
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    cancelled_date = serializers.DateField(
        source="program.cancelled_date",
        required=False,
        default=timezone.localdate,
    )
    cancelled_by = BaseUserSerializer(
        source="program.cancelled_by",
        read_only=True,
    )
    cancelled_at = serializers.DateTimeField(
        source="program.cancelled_at",
        read_only=True,
    )

    class Meta:
        model = CompositeProgram
        fields = [
            "cancellation_reason",
            "cancelled_date",
            "cancelled_by",
            "cancelled_at",
        ]

    def create(self, validated_data: dict) -> CompositeProgram:
        composite_program = validated_data.pop("composite_program")
        center = validated_data.pop("center")
        cancelled_by = validated_data.pop("cancelled_by")
        program_data = validated_data.pop("program", {})
        if not composite_program.program.is_active:
            raise serializers.ValidationError("Composite program is already cancelled.")
        if ServiceDocument.objects.filter(
                result__program_service__program=composite_program.program,
        ).exists():
            raise serializers.ValidationError(
                "Composite program cannot be cancelled since it has documents."
            )

        with transaction.atomic():
            composite_program.is_active = False
            cancellation_fields = {
                "is_active": False,
                "cancellation_reason": program_data.get("cancellation_reason"),
                "cancelled_by": cancelled_by,
                "cancelled_date": program_data.get("cancelled_date"),
            }
            for field, value in cancellation_fields.items():
                create_program_audit_log(
                    composite_program.program, field,
                    getattr(composite_program.program, field), value, cancelled_by,
                )
                setattr(composite_program.program, field, value)
            composite_program.save(update_fields=["is_active"])
            composite_program.program.save(
                update_fields=list(cancellation_fields)
            )
            cancel_all_program_services(
                composite_program.program.pk,
                center.pk,
                cancelled_by=cancelled_by,
                cancellation_reason=program_data.get("cancellation_reason"),
                cancelled_date=program_data.get("cancelled_date"),
            )
        composite_program.refresh_from_db(fields=["is_active"])
        composite_program.program.refresh_from_db(
            fields=[
                "is_active",
                "cancellation_reason",
                "cancelled_by",
                "cancelled_at",
                "cancelled_date",
            ]
        )
        return composite_program


class CompositeAddOnSerializer(BaseModelSerializer):
    id = serializers.UUIDField(source="pk", read_only=True)
    uid = serializers.CharField(source="program.uid", read_only=True)
    name = serializers.CharField(read_only=True)
    assessment_type = serializers.ChoiceField(
        choices=CompositeAssessmentType,
        read_only=True,
        allow_null=True,
    )
    assessment_type_code = serializers.CharField(
        source="assessment_type",
        read_only=True,
        allow_null=True,
    )
    profile = CustomerProfileWithCenterSerializer(
        source="program.customer_profile",
        read_only=True,
    )
    center = MinimumCenterSerializer(source="program.center", read_only=True)
    composite_template = BaseCompositeTemplateSerializer(read_only=True)
    program_type = serializers.ChoiceField(
        source="program.program_type",
        choices=ProgramType,
        read_only=True,
    )
    notes = serializers.CharField(source="program.notes", read_only=True)
    expires_at = serializers.DateField(
        source="program.expires_at",
        read_only=True,
    )
    is_complimentary = serializers.BooleanField(
        source="program.is_complimentary",
        read_only=True,
    )
    price = serializers.DecimalField(
        source="program.price",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )
    redeemable_centers = CompositeProgramCenterSerializer(
        source="program.redeemable_centers",
        many=True,
        read_only=True,
    )
    services = serializers.SerializerMethodField(read_only=True)
    services_count = serializers.IntegerField(
        source="program.services_count",
        read_only=True,
    )
    add_ons_count = serializers.IntegerField(read_only=True)
    assessment_services_count = serializers.IntegerField(read_only=True)
    therapy_services_count = serializers.IntegerField(read_only=True)
    consultation_services_count = serializers.IntegerField(read_only=True)
    consultation_documents_count = serializers.IntegerField(read_only=True)
    consultation_files_count = serializers.IntegerField(read_only=True)
    results_count = serializers.IntegerField(read_only=True)
    documents_count = serializers.IntegerField(read_only=True)
    reports_count = serializers.IntegerField(read_only=True)
    raw_data_count = serializers.IntegerField(read_only=True)
    redeemable_centers_count = serializers.IntegerField(
        source="program.redeemable_centers_count",
        read_only=True,
    )
    cancellation_reason = serializers.CharField(
        source="program.cancellation_reason",
        read_only=True,
    )
    cancelled_by = BaseUserSerializer(
        source="program.cancelled_by",
        read_only=True,
    )
    cancelled_at = serializers.DateTimeField(
        source="program.cancelled_at",
        read_only=True,
    )
    cancelled_date = serializers.DateField(
        source="program.cancelled_date",
        read_only=True,
    )
    created_date = serializers.DateField(
        source="program.created_date",
        read_only=True,
    )
    is_active = serializers.BooleanField(
        source="program.is_active",
        read_only=True,
    )
    created_at = serializers.DateTimeField(
        source="program.created_at",
        read_only=True,
    )
    updated_at = serializers.DateTimeField(
        source="program.updated_at",
        read_only=True,
    )
    created_by = BaseUserSerializer(
        source="program.created_by",
        read_only=True,
    )
    composite_program_id = serializers.UUIDField(write_only=True, required=True)
    add_services = CompositeAddOnServiceReferenceSerializer(
        many=True,
        required=True,
        allow_empty=False,
        write_only=True,
    )

    class Meta:
        model = CompositeProgram
        fields = [
            "id",
            "uid",
            "name",
            "assessment_type",
            "assessment_type_code",
            "profile",
            "center",
            "composite_template",
            "program_type",
            "notes",
            "expires_at",
            "is_complimentary",
            "price",
            "redeemable_centers",
            "redeemable_centers_count",
            "services",
            "services_count",
            "add_ons_count",
            "assessment_services_count",
            "therapy_services_count",
            "consultation_services_count",
            "consultation_documents_count",
            "consultation_files_count",
            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
            "created_date",
            "is_active",
            "created_at",
            "updated_at",
            "created_by",
            "composite_program_id",
            "add_services",
        ]

    @classmethod
    def validate_composite_program(
            cls,
            composite_program: CompositeProgram | None,
    ):
        if not composite_program:
            raise serializers.ValidationError(
                {"composite_program_id": "Invalid composite program ID provided."}
            )
        if (
                not composite_program.is_active
                or not composite_program.program.is_active
        ):
            raise serializers.ValidationError(
                {"composite_program_id": "Composite program is inactive or cancelled."}
            )
        expires_at = composite_program.program.expires_at
        if expires_at and expires_at < timezone.localdate():
            raise serializers.ValidationError(
                {"composite_program_id": "Composite program has expired."}
            )
        return composite_program

    @classmethod
    def get_add_on_services(
            cls,
            service_data: list[dict],
    ):
        service_identifiers = {service["id"] for service in service_data}
        services = list(
            Service.objects.filter(
                pk__in=service_identifiers,
                is_active=True,
                service_category__in=[
                    ServiceCategory.ASSESSMENT,
                    ServiceCategory.THERAPY,
                    ServiceCategory.CONSULTATION,
                ],
            )
        )
        services_by_primary_key = {service.pk: service for service in services}
        invalid_service_identifiers = service_identifiers - set(
            services_by_primary_key
        )
        if invalid_service_identifiers:
            invalid_identifiers = ", ".join(
                str(service_identifier)
                for service_identifier in sorted(
                    invalid_service_identifiers,
                    key=str,
                )
            )
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "Invalid, inactive, or unsupported service IDs provided: "
                        f"{invalid_identifiers}."
                    )
                }
            )
        return services_by_primary_key

    @classmethod
    def get_service_quantities(
            cls,
            service_data: list[dict],
            services_by_primary_key: dict[UUID, Service],
    ):
        missing_quantity_positions = [
            position
            for position, service_entry in enumerate(service_data, start=1)
            if (
                    services_by_primary_key[
                        service_entry["id"]
                    ].service_category == ServiceCategory.THERAPY
                    and service_entry.get("sessions_count") is None
            )
        ]
        if missing_quantity_positions:
            positions = ", ".join(map(str, missing_quantity_positions))
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "Quantity is required for therapy service entries at "
                        f"positions: {positions}."
                    )
                }
            )

        invalid_quantity_positions = [
            position
            for position, service_entry in enumerate(service_data, start=1)
            if (
                    services_by_primary_key[
                        service_entry["id"]
                    ].service_category in [
                        ServiceCategory.ASSESSMENT,
                        ServiceCategory.CONSULTATION,
                    ]
                    and service_entry.get("sessions_count") is not None
            )
        ]
        if invalid_quantity_positions:
            positions = ", ".join(map(str, invalid_quantity_positions))
            raise serializers.ValidationError(
                {
                    "add_services": (
                        "Quantity is only supported for therapy service entries. "
                        f"Remove it from positions: {positions}."
                    )
                }
            )

        return [service_entry.get("sessions_count") for service_entry in service_data]

    @classmethod
    def get_service_centers(
            cls,
            composite_program: CompositeProgram,
            service_data: list[dict],
            services_by_primary_key: dict[UUID, Service],
    ):
        """Validate explicit add-on centers; omitted selections remain empty."""
        service_identifiers = set()
        requested_center_identifiers = set()
        for service_entry in service_data:
            service_identifiers.add(service_entry["id"])
            for center_selection in service_entry.get("centers", []):
                requested_center_identifiers.add(center_selection["id"])
        center_filters = {}
        if not composite_program.therapy_redemption_is_global:
            center_filters["redeemable_programs"] = composite_program.program
        allowed_centers = {}
        for center in Center.objects.filter(
                pk__in=requested_center_identifiers,
                is_active=True,
                customer_assignments__customer_profile=composite_program.program.customer_profile,
                customer_assignments__is_active=True,
                **center_filters,
        ):
            allowed_centers[center.pk] = center
        available_pairs = set(
            CenterServiceAssignment.objects.filter(
                service__pk__in=service_identifiers,
                center__pk__in=requested_center_identifiers,
                center__is_active=True,
                is_active=True,
            ).values_list("service__pk", "center__pk")
        )
        service_centers = []
        errors = []
        for service_entry in service_data:
            service = services_by_primary_key[service_entry["id"]]
            is_therapy = service.service_category == ServiceCategory.THERAPY
            entry_errors = {}
            if "centers" in service_entry and not is_therapy:
                entry_errors["centers"] = [
                    "Center selections are only supported for therapy service entries."
                ]
            if not is_therapy:
                service_centers.append([])
                errors.append(entry_errors)
                continue
            center_selections = service_entry.get("centers", [])
            center_identifiers = set()
            for center_selection in center_selections:
                center_identifiers.add(center_selection["id"])
            center_errors = []
            if center_identifiers - allowed_centers.keys():
                center_errors.append(
                    "Centers must be active customer centers within the program's redemption scope."
                )
            for center_identifier in center_identifiers:
                if (service.pk, center_identifier) not in available_pairs:
                    center_errors.append(
                        f"This service is not available at center {center_identifier}."
                    )
            centers = []
            if center_errors:
                entry_errors["centers"] = center_errors
            else:
                for center_identifier in center_identifiers:
                    centers.append(allowed_centers[center_identifier])
            service_centers.append(centers)
            errors.append(entry_errors)
        if any(errors):
            raise serializers.ValidationError({"add_services": errors})
        return service_centers

    def create(self, validated_data: dict):
        service_data = validated_data.pop("add_services")
        created_by = validated_data.pop("created_by")
        composite_program = validated_data.pop("composite_program")

        with transaction.atomic():
            composite_program = self.validate_composite_program(
                composite_program,
            )
            services_by_primary_key = self.get_add_on_services(
                service_data
            )
            service_quantities = self.get_service_quantities(
                service_data,
                services_by_primary_key,
            )
            service_centers = self.get_service_centers(
                composite_program,
                service_data,
                services_by_primary_key,
            )
            program_services = [
                ProgramService(
                    program=composite_program.program,
                    service=services_by_primary_key[service_entry["id"]],
                    assignment_type=ServiceAssignment.ADD_ON,
                    created_by=created_by,
                )
                for service_entry in service_data
            ]
            ProgramService.objects.bulk_create(program_services)
            create_program_service_extensions(
                program_services,
                service_quantities,
                service_centers,
            )
            update_program_services_count(composite_program.program.pk)
            update_composite_program_service_counts(
                composite_program.program.pk
            )
            composite_program.refresh_from_db(
                fields=[
                    "add_ons_count",
                    "assessment_services_count",
                    "therapy_services_count",
                    "consultation_services_count",
                ]
            )
            composite_program.program.refresh_from_db(fields=["services_count"])
        return composite_program

    def get_services(self, instance):
        program_services = getattr(instance.program, "service_preview", None)
        if not program_services:
            return None
        return CompositeProgramServiceSerializer(
            program_services[:5],
            many=True,
            context=self.context,
        ).data
