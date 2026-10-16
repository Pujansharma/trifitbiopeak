from pathlib import Path

from django.db import transaction
from django.utils import timezone
from rest_framework import serializers

from accounts.users.serializers import BaseUserSerializer
from core.utils.serializers import BaseModelSerializer
from integrations.bugspeaks.utils.webhooks import get_bugspeaks_lifecycle
from integrations.metsights.tasks import start_metsights_refetch_task
from integrations.strand_genomics.utils.webhooks import get_strand_lifecycle
from products.models import Product
from products.serializers import BaseProductSerializer, BaseProviderSerializer
from products.utils.constants import ProductCallbackFunction, ProviderCallbackFunction
from products.utils.documents import get_allowed_document_type_choices
from programs.composites.utils.db import (
    update_composite_program_document_counts,
    update_composite_program_results_count,
)
from programs.models import ProgramService, TherapyProgramService
from programs.program_services.bookings import start_provider_fetch_task
from programs.program_services.tasks import (
    get_result_fetch_handler,
    start_result_request_task,
)
from programs.program_services.utils.db import (
    delete_service_result,
    update_program_service_document_counts,
    update_program_service_fetch_counts,
    update_program_service_results_count,
    update_result_documents_count,
)
from programs.program_services.utils.helper import generate_file_hash
from programs.program_services.utils.order_results import PROVIDER_ORDER_REPORT_HANDLERS
from programs.program_services.utils.report_requests import get_report_request_handler
from programs.program_services.utils.validation import validate_configured_payload
from programs.serializers import BaseProgramSerializer
from programs.services.models import ResultRequest, ServiceDocument, ServiceResult
from programs.services.serializers import (
    BaseServiceDocumentModuleCategorySerializer,
    BaseServiceSerializer,
    ResultRequestFilesSerializer,
)
from programs.services.utils.constants import (
    RequestResultType,
    ResultRequestStatus,
    ResultType,
    ServiceCategory,
    ServiceDocumentType,
)
from programs.utils.db import cancel_program_service

PROVIDER_LIFECYCLE_HANDLERS = {
    (RequestResultType.ORDER, ProviderCallbackFunction.BUGSPEAKS): get_bugspeaks_lifecycle,
    (RequestResultType.ORDER, ProviderCallbackFunction.STRAND_LIFE_SCIENCES): get_strand_lifecycle,
}


class BaseServiceResultSerializer(BaseModelSerializer):
    result_mode_code = serializers.CharField(
        source="result_mode",
        read_only=True,
    )
    document_type_code = serializers.CharField(
        source="document_type",
        read_only=True,
    )

    class Meta:
        model = ServiceResult
        fields = [
            "id",
            "provider_name",
            "product_name",
            "result_mode",
            "result_mode_code",
            "document_type",
            "document_type_code",
            "sample_collection_date",
            "report_generation_date",
        ]
        read_only_fields = [
            "id",
            "provider_name",
            "product_name",
            "result_mode",
            "document_type",
            "sample_collection_date",
            "report_generation_date",
        ]


class BaseAssessmentServiceDocumentSerializer(
    BaseServiceDocumentModuleCategorySerializer
):
    document_category_code = serializers.CharField(
        source="document_category",
        read_only=True,
    )

    class Meta:
        model = ServiceDocument
        fields = [
            "id",
            "file",
            "filename",
            "content_type",
            "document_category",
            "document_category_code",
            "module_category",
            "module_category_code",
        ]


class AssessmentServiceResultRequestHistorySerializer(ResultRequestFilesSerializer):
    provider = BaseProviderSerializer(source="product.provider", read_only=True)
    product = BaseProductSerializer(read_only=True)
    data = serializers.JSONField(required=False)
    profile_data = serializers.JSONField(required=False)
    provider_lifecycle = serializers.SerializerMethodField()
    request_type_code = serializers.CharField(source="request_type", read_only=True)
    status_code = serializers.CharField(source="status", read_only=True)
    results = BaseServiceResultSerializer(many=True, read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ResultRequest
        fields = [
            "id", "provider", "product", "data", "profile_data", "files", "provider_lifecycle",
            "status", "status_code",
            "request_type", "request_type_code", "is_submitted", "attempts_count",
            "failure_detail", "started_at", "completed_at", "results", "created_by",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "request_type",
            "is_submitted",
            "attempts_count",
            "failure_detail",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]

    @classmethod
    def get_provider_lifecycle(cls, instance: ResultRequest) -> dict | None:
        handler = PROVIDER_LIFECYCLE_HANDLERS.get(
            (instance.request_type, instance.product.provider.callback),
        )
        if not handler:
            return None
        return handler(instance)

    def update(self, instance: ResultRequest, validated_data):
        if instance.request_type != RequestResultType.ORDER:
            raise serializers.ValidationError("Only orders can be edited.")
        if instance.status != ResultRequestStatus.PENDING:
            raise serializers.ValidationError("Only pending orders can be edited.")
        if instance.is_submitted:
            raise serializers.ValidationError("Submitted orders cannot be edited.")
        provider = instance.product.provider
        _data = instance.data or {}
        booking_data = _data
        if provider.callback == ProviderCallbackFunction.METFLUX:
            booking_data = _data.get("booking") or {}
        booking = validate_configured_payload(
            "data", validated_data.get("data", booking_data), provider.booking_fields,
        )
        profile = validate_configured_payload(
            "profile_data", validated_data.get("profile_data", instance.profile_data or {}),
            provider.booking_profile_fields,
        )
        if provider.callback == ProviderCallbackFunction.METFLUX:
            booking = {"booking": booking}
        _data.update(booking)
        validated_data["data"] = _data
        validated_data["profile_data"] = profile
        return super().update(instance, validated_data)


class AssessmentServiceResultRequestSerializer(BaseModelSerializer):
    provider = BaseProviderSerializer(source="product.provider", read_only=True)
    provider_id = serializers.UUIDField(write_only=True)
    product = BaseProductSerializer(read_only=True)
    product_id = serializers.UUIDField(write_only=True)
    data = serializers.JSONField(write_only=True)
    profile_data = serializers.JSONField(write_only=True)
    request_type_code = serializers.CharField(source="request_type", read_only=True)
    status_code = serializers.CharField(source="status", read_only=True)
    results = BaseServiceResultSerializer(many=True, read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ResultRequest
        fields = [
            "id",
            "provider",
            "provider_id",
            "product",
            "product_id",
            "data",
            "profile_data",
            "status",
            "status_code",
            "request_type",
            "request_type_code",
            "attempts_count",
            "failure_detail",
            "started_at",
            "completed_at",
            "results",
            "created_by",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "attempts_count",
            "failure_detail",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data):
        program_service = validated_data.pop("program_service")
        created_by = validated_data.pop("created_by")
        provider_identifier = validated_data.pop("provider_id")
        product_identifier = validated_data.pop("product_id")
        product = (
            Product.objects.filter(
                pk=product_identifier,
                provider__pk=provider_identifier,
                provider__is_active=True,
                provider__is_api_enabled=True,
                provider__api__is_active=True,
                is_active=True,
                service_assignments__service=program_service.service,
                service_assignments__is_active=True,
            )
            .select_related("provider", "provider__api")
            .first()
        )
        if not product:
            raise serializers.ValidationError(
                {"product_id": "This product is not available for result fetching."}
            )

        handler = get_result_fetch_handler(
            product.provider.callback,
            product.callback,
        )
        if not handler:
            raise serializers.ValidationError(
                {"product_id": "Result fetching is not supported for this product."}
            )

        validated_data["data"] = validate_configured_payload(
            "data",
            validated_data["data"],
            product.provider.fetch_fields,
        )
        validated_data["profile_data"] = validate_configured_payload(
            "profile_data",
            validated_data["profile_data"],
            product.provider.fetch_profile_fields,
        )
        validated_data["program_service"] = program_service
        validated_data["product"] = product
        validated_data["created_by"] = created_by

        validated_data["request_type"] = RequestResultType.FETCH
        validated_data["is_submitted"] = False
        result_request = super().create(validated_data)
        update_program_service_fetch_counts(program_service.pk)
        start_result_request_task(result_request)
        return result_request


class AssessmentServiceReportRequestSerializer(BaseModelSerializer):
    product_id = serializers.UUIDField(write_only=True)
    data = serializers.JSONField(required=False, default=dict, write_only=True)
    profile_data = serializers.JSONField(required=False, default=dict, write_only=True)
    product = BaseProductSerializer(read_only=True)
    request_type_code = serializers.CharField(source="request_type", read_only=True)
    status_code = serializers.CharField(source="status", read_only=True)

    class Meta:
        model = ResultRequest
        fields = [
            "id", "product_id", "product", "data", "profile_data", "status", "status_code",
            "request_type", "request_type_code", "is_submitted",
            "attempts_count", "failure_detail", "started_at", "completed_at",
            "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "status", "request_type", "is_submitted", "attempts_count", "failure_detail",
            "started_at", "completed_at", "created_at", "updated_at",
        ]

    def create(self, validated_data):
        program_service = validated_data["program_service"]
        product = Product.objects.filter(
            pk=validated_data.pop("product_id"), is_active=True,
            provider__is_active=True,
            service_assignments__service=program_service.service,
            service_assignments__is_active=True,
        ).select_related("provider__api").first()
        if not program_service.is_active or not product:
            raise serializers.ValidationError(
                {"product_id": "An active product and program service are required."}
            )
        handler = get_report_request_handler(product.provider.callback, product.callback)
        if not handler:
            raise serializers.ValidationError(
                {"product_id": "Report requesting is not supported for this product."}
            )
        provider = product.provider
        booking_data = validate_configured_payload(
            "data", validated_data.get("data", {}), provider.booking_fields,
        )
        profile_data = validate_configured_payload(
            "profile_data", validated_data.get("profile_data", {}), provider.booking_profile_fields,
        )
        if provider.callback == ProviderCallbackFunction.METFLUX:
            booking_data = {"booking": booking_data}
        validated_data.update(
            product=product, request_type=RequestResultType.ORDER,
            data=booking_data, profile_data=profile_data,
            status=ResultRequestStatus.PENDING, is_submitted=False,
        )
        with transaction.atomic():
            result_request = super().create(validated_data)
            update_program_service_fetch_counts(program_service.pk)
        return result_request


class ResultRequestRefetchSerializer(BaseModelSerializer):
    provider = BaseProviderSerializer(source="product.provider", read_only=True)
    product = BaseProductSerializer(read_only=True)
    request_type_code = serializers.CharField(source="request_type", read_only=True)
    status_code = serializers.CharField(source="status", read_only=True)
    results = BaseServiceResultSerializer(many=True, read_only=True)

    class Meta:
        model = ResultRequest
        fields = [
            "id",
            "provider",
            "product",
            "data",
            "status",
            "status_code",
            "request_type",
            "request_type_code",
            "is_submitted",
            "attempts_count",
            "failure_detail",
            "started_at",
            "completed_at",
            "results",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def create(self, validated_data):
        result_request = validated_data.pop("result_request")
        if result_request.request_type == RequestResultType.ORDER and not result_request.is_submitted:
            raise serializers.ValidationError("An unsubmitted order cannot be refetched. Confirm it first.")
        if result_request.request_type == RequestResultType.ORDER and result_request.status == ResultRequestStatus.CANCELLED:
            raise serializers.ValidationError(
                "A cancelled order request cannot be refetched."
            )

        provider = result_request.product.provider
        provider_api = getattr(provider, "api", None)
        handler = get_result_fetch_handler(provider.callback, result_request.product.callback)
        if result_request.request_type == RequestResultType.ORDER:
            provider_handlers = PROVIDER_ORDER_REPORT_HANDLERS.get(provider.callback) or {}
            handler = provider_handlers.get(result_request.product.callback)
            if provider.callback == ProviderCallbackFunction.METFLUX:
                handler = {
                    ProductCallbackFunction.METSIGHTS_PP: start_metsights_refetch_task,
                }.get(result_request.product.callback)
        if (
                not result_request.program_service.is_active
                or not result_request.product.is_active
                or not provider.is_active
                or not provider.is_api_enabled
                or not provider_api
                or not provider_api.is_active
                or not handler
        ):
            raise serializers.ValidationError(
                "This result request is not currently available for refetching."
            )

        program_service = result_request.program_service
        with transaction.atomic():
            for service_result in ServiceResult.objects.filter(result_request=result_request).iterator():
                delete_service_result(service_result)
            getattr(result_request, "_prefetched_objects_cache", {}).pop("results", None)
            if (
                result_request.request_type == RequestResultType.ORDER
                and provider.callback == ProviderCallbackFunction.METFLUX
            ):
                result_request.data.pop("artifacts", None)
                result_request.data.pop("fetch_errors", None)
            result_request.status = ResultRequestStatus.QUEUED
            result_request.failure_detail = ""
            result_request.started_at = None
            result_request.completed_at = None
            result_request.save(
                update_fields=[
                    "status",
                    "data",
                    "failure_detail",
                    "started_at",
                    "completed_at",
                    "updated_at",
                ]
            )
            update_program_service_results_count(program_service.pk)
            update_program_service_document_counts(program_service.pk)
            update_program_service_fetch_counts(program_service.pk)
            update_composite_program_results_count(program_service.program.pk)
            update_composite_program_document_counts(program_service.program.pk)

        if result_request.request_type == RequestResultType.ORDER:
            refetch_worker = {
                ProviderCallbackFunction.METFLUX: start_metsights_refetch_task,
            }.get(provider.callback, start_provider_fetch_task)
            refetch_worker(result_request)
            return result_request

        start_result_request_task(result_request)
        return result_request


class ResultRequestCancelSerializer(BaseModelSerializer):
    provider = BaseProviderSerializer(source="product.provider", read_only=True)
    product = BaseProductSerializer(read_only=True)
    request_type_code = serializers.CharField(source="request_type", read_only=True)
    status_code = serializers.CharField(source="status", read_only=True)
    results = BaseServiceResultSerializer(many=True, read_only=True)

    class Meta:
        model = ResultRequest
        fields = [
            "id",
            "provider",
            "product",
            "data",
            "status",
            "status_code",
            "request_type",
            "request_type_code",
            "is_submitted",
            "attempts_count",
            "failure_detail",
            "started_at",
            "completed_at",
            "results",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields

    def create(self, validated_data):
        result_request = validated_data.pop("result_request")
        if result_request.status == ResultRequestStatus.CANCELLED:
            raise serializers.ValidationError(
                "Result request is already cancelled."
            )
        if result_request.status == ResultRequestStatus.COMPLETED:
            raise serializers.ValidationError(
                "A completed result request cannot be cancelled."
            )

        result_request.status = ResultRequestStatus.CANCELLED
        result_request.save(update_fields=["status", "updated_at"])
        update_program_service_fetch_counts(result_request.program_service.pk)
        return result_request


class AssessmentServiceResultSerializer(BaseModelSerializer):
    product = BaseProductSerializer(read_only=True)
    product_id = serializers.UUIDField(
        required=True,
        write_only=True,
    )
    result_mode_code = serializers.CharField(
        source="result_mode",
        read_only=True,
    )
    document_type = serializers.ChoiceField(
        choices=ServiceDocumentType,
        required=True,
    )
    document_type_code = serializers.CharField(
        source="document_type",
        read_only=True,
    )
    documents_count = serializers.IntegerField(read_only=True, default=0)
    created_by = BaseUserSerializer(read_only=True)

    documents = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = ServiceResult
        fields = [
            "id",
            "product",
            "product_id",
            "provider_name",
            "product_name",
            "result_mode",
            "result_mode_code",
            "document_type",
            "document_type_code",
            "sample_collection_date",
            "report_generation_date",
            "documents_count",
            'documents',
            "created_by",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "provider_name",
            "product_name",
            "result_mode",
            "documents_count",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def get_documents(self, instance):
        _documents = getattr(instance, 'documents', None)
        if not _documents:
            return None
        qs = _documents.all()[:3]
        return BaseAssessmentServiceDocumentSerializer(
            qs, many=True, context=self.context
        ).data

    @classmethod
    def get_assigned_product(
            cls,
            program_service: ProgramService,
            product_identifier,
    ):
        product = (
            Product.objects.filter(
                pk=product_identifier,
                is_active=True,
                provider__is_active=True,
                service_assignments__service=program_service.service,
                service_assignments__is_active=True,
            )
            .select_related("provider")
            .first()
        )
        if not product:
            raise serializers.ValidationError(
                {"product_id": "This product is not available for the service."}
            )
        return product

    @classmethod
    def _validate_document_type(cls, product: Product, document_type):
        allowed_document_types = get_allowed_document_type_choices(
            product.provider.callback,
            product.callback,
        )
        if document_type not in allowed_document_types:
            raise serializers.ValidationError(
                {
                    "document_type": (
                        "This document type is not allowed for the selected product."
                    )
                }
            )

    @classmethod
    def set_product_metadata(cls, validated_data: dict, product: Product):
        validated_data["product"] = product
        validated_data["provider_name"] = product.provider.name
        validated_data["product_name"] = product.name

    def create(self, validated_data: dict):
        program_service = validated_data.pop("program_service")
        created_by = validated_data.pop("created_by")
        product_identifier = validated_data.pop("product_id")

        with transaction.atomic():
            current_program_service = (
                ProgramService.objects.select_related("service", "program")
                .filter(pk=program_service.pk)
                .first()
            )
            if not current_program_service or not current_program_service.is_active:
                raise serializers.ValidationError(
                    "An inactive program service cannot receive results."
                )
            product = self.get_assigned_product(
                current_program_service,
                product_identifier,
            )
            self._validate_document_type(product, validated_data["document_type"])
            self.set_product_metadata(validated_data, product)
            validated_data["program_service"] = current_program_service
            validated_data["created_by"] = created_by
            validated_data["result_mode"] = ResultType.UPLOAD
            service_result = super().create(validated_data)
            update_program_service_results_count(current_program_service.pk)
            update_composite_program_results_count(
                current_program_service.program.pk
            )
        return service_result

    def update(self, instance: ServiceResult, validated_data: dict):
        validated_data.pop('product_id', None)
        validated_data.pop("document_type", None)
        return super().update(instance, validated_data)


class AssessmentServiceDocumentSerializer(
    BaseServiceDocumentModuleCategorySerializer
):
    document_category_code = serializers.CharField(
        source="document_category",
        read_only=True,
    )

    class Meta:
        model = ServiceDocument
        fields = [
            "id",
            "file",
            "filename",
            "content_type",
            "document_category",
            "document_category_code",
            "module_category",
            "module_category_code",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "filename",
            "content_type",
            "is_active",
            "created_at",
            "updated_at",
        ]

    def create(self, validated_data: dict):
        service_result = validated_data.pop("result")
        uploaded_file = validated_data.get("file")
        program_service_identifier = service_result.program_service.pk

        with transaction.atomic():
            program_service = (
                ProgramService.objects.select_related("program")
                .filter(pk=program_service_identifier)
                .first()
            )
            current_service_result = (
                ServiceResult.objects.filter(pk=service_result.pk)
                .first()
            )
            if not program_service or not program_service.is_active:
                raise serializers.ValidationError(
                    "An inactive program service cannot receive documents."
                )
            if not current_service_result or not current_service_result.is_active:
                raise serializers.ValidationError(
                    "An inactive result cannot receive documents."
                )
            validated_data["result"] = current_service_result
            validated_data["filename"] = Path(uploaded_file.name).name
            validated_data["content_type"] = (
                    uploaded_file.content_type or "application/octet-stream"
            )
            validated_data["file_hash"] = generate_file_hash(uploaded_file)
            service_document = super().create(validated_data)
            update_result_documents_count(current_service_result.pk)
            update_program_service_document_counts(program_service.pk)
            update_program_service_fetch_counts(program_service.pk)
            update_composite_program_document_counts(
                program_service.program.pk
            )
        return service_document


class ProgramServiceCancelSerializer(BaseModelSerializer):
    cancellation_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        allow_null=True,
    )
    cancelled_by = BaseUserSerializer(read_only=True)
    cancelled_at = serializers.DateTimeField(read_only=True)
    cancelled_date = serializers.DateField(
        required=False,
        default=timezone.localdate,
    )

    class Meta:
        model = ProgramService
        fields = [
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
        ]

    def create(self, validated_data: dict):
        program_service = validated_data.pop("program_service")
        cancelled_by = validated_data.pop("cancelled_by")
        center = validated_data.pop("center", None)
        if not program_service.is_active:
            raise serializers.ValidationError("Program service is already cancelled.")

        if program_service.service.service_category == ServiceCategory.THERAPY:
            therapy_program_service = (
                TherapyProgramService.objects.filter(program_service=program_service)
                .select_related("program_service")
                .first()
            )
            if therapy_program_service and (
                    therapy_program_service.sessions_used
                    >= therapy_program_service.sessions_count
            ):
                raise serializers.ValidationError(
                    "Service cannot be cancelled since it is already used"
                )

        cancel_program_service(
            program_service.pk,
            program_service.program.pk,
            center_id=center.pk if center else None,
            cancelled_by=cancelled_by,
            cancellation_reason=validated_data.get("cancellation_reason"),
            cancelled_date=validated_data.get("cancelled_date", timezone.localdate()),
        )
        program_service.refresh_from_db(
            fields=[
                "is_active",
                "cancellation_reason",
                "cancelled_by",
                "cancelled_at",
                "cancelled_date",
            ]
        )
        return program_service


class AssessmentProgramServiceSerializer(BaseModelSerializer):
    service = BaseServiceSerializer(read_only=True)
    data = serializers.JSONField(read_only=True)
    assignment_type_code = serializers.CharField(
        source="assignment_type",
        read_only=True,
    )
    cancelled_by = BaseUserSerializer(read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ProgramService
        fields = [
            "id",
            "service",
            "data",
            "assignment_type",
            "assignment_type_code",
            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "fetch_count",
            "fetch_results_count",
            "fetch_documents_count",
            "fetch_pending_count",
            "created_date",
            "created_by",
            "is_active",
            "created_at",
            "updated_at",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
        ]
        read_only_fields = [
            "id",
            "assignment_type",
            "results_count",
            "documents_count",
            "reports_count",
            "raw_data_count",
            "fetch_count",
            "fetch_results_count",
            "fetch_documents_count",
            "fetch_pending_count",
            "created_date",
            "is_active",
            "created_at",
            "updated_at",
            "cancellation_reason",
            "cancelled_at",
            "cancelled_date",
        ]


class TherapyProgramServiceSerializer(BaseModelSerializer):
    program = BaseProgramSerializer(read_only=True)
    service = BaseServiceSerializer(read_only=True)
    assignment_type_code = serializers.CharField(
        source="assignment_type",
        read_only=True,
    )
    sessions_count = serializers.IntegerField(
        source="therapy_service.sessions_count",
        read_only=True,
        default=None,
        allow_null=True,
    )
    sessions_used = serializers.IntegerField(
        source="therapy_service.sessions_used",
        read_only=True,
        default=None,
        allow_null=True,
    )
    sessions_cancelled = serializers.IntegerField(
        source="therapy_service.sessions_cancelled",
        read_only=True,
        default=None,
        allow_null=True,
    )
    redeem_code = serializers.CharField(
        source="therapy_service.redeem_code",
        read_only=True,
        default=None,
        allow_null=True,
    )
    cancelled_by = BaseUserSerializer(read_only=True)
    created_by = BaseUserSerializer(read_only=True)

    class Meta:
        model = ProgramService
        fields = [
            "id",
            "program",
            "service",
            "assignment_type",
            "assignment_type_code",
            "sessions_count",
            "sessions_used",
            "sessions_cancelled",
            "redeem_code",
            "created_date",
            "created_by",
            "is_active",
            "created_at",
            "updated_at",
            "cancellation_reason",
            "cancelled_by",
            "cancelled_at",
            "cancelled_date",
        ]
        read_only_fields = [
            "id",
            "assignment_type",
            "created_date",
            "is_active",
            "created_at",
            "updated_at",
            "cancellation_reason",
            "cancelled_at",
            "cancelled_date",
        ]
