from django.db.models import Exists, F, OuterRef, Prefetch, Q, QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError
from rest_framework.mixins import UpdateModelMixin
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.centers.models import Center
from accounts.customers.models import CustomerCenterAssignment
from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from accounts.utils.permissions import BaseAssociateRBACPermission, IsAdminUser, IsAssociateUser, IsCustomerUser
from core.utils.exceptions import get_object_or_404
from core.utils.helper import response_format
from core.utils.permissions import ReadOnly
from core.utils.views.main import (
    BaseCreateAPIView,
    BaseDestroyAPIView,
    BaseGenericAPIView,
    BaseListAPIView,
    BaseListCreateAPIView,
    BaseRetrieveAPIView,
    BaseRetrieveDestroyAPIView,
    BaseRetrieveUpdateAPIView,
)
from integrations.confirmation import OrderConfirmationSerializer
from products.models import Product, Provider
from products.serializers import (
    AssessmentServiceProviderSerializer,
    BaseProductSerializer,
)
from products.utils.constants import ProviderCallbackFunction
from programs.models import ProgramService, TherapyProgramService
from programs.program_services.serializers import (
    AssessmentProgramServiceSerializer,
    AssessmentServiceDocumentSerializer,
    AssessmentServiceResultRequestHistorySerializer,
    AssessmentServiceReportRequestSerializer,
    AssessmentServiceResultRequestSerializer,
    AssessmentServiceResultSerializer,
    ConsultationProgramServiceSerializer,
    ProgramServiceCancelSerializer,
    ResultRequestCancelSerializer,
    ResultRequestRefetchSerializer,
    TherapyProgramServiceCentersSerializer,
    TherapyProgramServiceDiscardSerializer,
    TherapyProgramServiceSerializer,
)
from programs.program_services.utils.db import (
    delete_service_document,
    delete_service_result,
)
from programs.serializers import TherapyServiceAvailableRedeemableCenterSerializer
from programs.services.models import (
    CenterServiceAssignment,
    ResultRequest,
    ResultRequestFile,
    ServiceDocument,
    ServiceResult,
)
from programs.services.serializers import ResultRequestFileSerializer
from programs.services.utils.constants import (
    RequestResultType,
    ServiceCategory,
    get_module_category_document_types, ResultRequestStatus,
)
from programs.utils.constants import ProgramType


class ProgramServiceCancelViewMeta(BaseGenericAPIView):
    service_category = None
    program_service_filter_kwargs = {}

    def get_program_service_queryset(self):
        program_services = ProgramService.objects.filter(
            service__service_category=self.service_category,
            **self.program_service_filter_kwargs,
        ).select_related(
            "program",
            "service",
        )
        return program_services

    def get_program_service(self):
        return get_object_or_404(
            self.get_program_service_queryset(),
            "Program service not found.",
            pk=self.kwargs["pk"],
        )


class AssessmentProgramServiceViewMeta(BaseGenericAPIView):
    def get_assessment_program_service_queryset(self):
        program_services = ProgramService.objects.filter(
            service__service_category=ServiceCategory.ASSESSMENT,
        ).select_related("service")
        return program_services

    def get_assessment_program_service(self):
        return get_object_or_404(
            self.get_assessment_program_service_queryset(),
            "Assessment program service not found.",
            pk=self.kwargs["pk"],
        )

    def get_active_assessment_program_service(self):
        program_services = self.get_assessment_program_service_queryset().filter(
            is_active=True
        )
        return get_object_or_404(
            program_services,
            "Assessment program service not found.",
            pk=self.kwargs["pk"],
        )

    def get_service_result_queryset(self):
        service_results = (
            ServiceResult.objects.filter(
                program_service__service__service_category=(
                    ServiceCategory.ASSESSMENT
                ),
            )
            .select_related(
                "program_service",
                "program_service__service",
                "product",
                "product__provider",
                "created_by",
            )
            .prefetch_related(
                'documents'
            )

        )
        return service_results

    def get_service_document_queryset(self):
        service_documents = ServiceDocument.objects.filter(
            result__program_service__service__service_category=(
                ServiceCategory.ASSESSMENT
            ),
        ).select_related(
            "result",
            "result__program_service",
        )
        return service_documents


class AssignedCompositeServiceViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_queryset(self):
        program_services = ProgramService.objects.filter(
            program__program_type=ProgramType.COMPOSITE,
            **self.filter_kwargs,
        ).select_related(
            "program__composite_program", "program__customer_profile__customer__user",
            "service", "therapy_service", "consultation_service", "created_by", "cancelled_by",
        ).prefetch_related("therapy_service__redeemable_centers")
        if get_user_account_type(self.request.user) == UserType.ASSOCIATE:
            program_services = program_services.filter(
                Q(program__center__pk=self.request.center_id)
                | Q(program__redeemable_centers__pk=self.request.center_id)
            )
        return program_services.distinct()


class ConsultationProgramServiceDetailView(BaseRetrieveAPIView, AssignedCompositeServiceViewMeta):
    serializer_class = ConsultationProgramServiceSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]
    filter_kwargs = {
        "service__service_category": ServiceCategory.CONSULTATION,
        "consultation_service__isnull": False,
    }


class TherapyProgramServiceViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_therapy_service_queryset(self):
        filter_kwargs = {}
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.CUSTOMER:
            filter_kwargs["program_service__program__customer_profile__customer"] = self.request.user.customer
        return TherapyProgramService.objects.filter(**filter_kwargs).select_related(
            "program_service__program__customer_profile",
            "program_service__program__composite_program",
        )

    def get_therapy_service(self):
        return get_object_or_404(
            self.get_therapy_service_queryset(),
            "Therapy program service not found.",
            pk=self.kwargs["pk"],
        )


class TherapyProgramServiceRedeemableCentersView(BaseListAPIView, TherapyProgramServiceViewMeta):
    serializer_class = TherapyProgramServiceCentersSerializer
    permission_classes = [
        IsAdminUser | ((IsAssociateUser | IsCustomerUser) & ReadOnly) | BaseAssociateRBACPermission
    ]

    def get_queryset(self):
        therapy_service = self.get_therapy_service()
        program = therapy_service.program_service.program
        can_redeem_subquery = Center.objects.filter(
            pk=OuterRef("pk"),
            redeemable_programs=program,
        )
        if program.program_type == ProgramType.THERAPY:
            can_redeem_subquery = TherapyProgramService.objects.filter(
                pk=therapy_service.pk,
                is_discarded=False,
                program_service__program__therapy_program__is_discarded=False,
                program_service__program__redeemable_centers__pk=OuterRef("pk"),
            )
        if program.program_type == ProgramType.COMPOSITE:
            redemption_center = F("program_service__service__center_assignments__center")
            selected_centers = TherapyProgramService.objects.filter(
                pk=OuterRef("pk"), redeemable_centers__isnull=False,
            )
            can_redeem_subquery = TherapyProgramService.objects.filter(
                Q(program_service__program__expires_at__isnull=True)
                | Q(program_service__program__expires_at__gte=timezone.localdate()),
                Q(program_service__program__composite_program__therapy_redemption_is_global=True)
                | Q(program_service__program__redeemable_centers=redemption_center),
                Q(redeemable_centers=redemption_center)
                | Q(
                    ~Exists(selected_centers),
                    program_service__program__composite_program__therapy_redemption_is_global=True,
                ),
                pk=therapy_service.pk,
                is_active=True,
                program_service__is_active=True,
                program_service__program__program_type=ProgramType.COMPOSITE,
                program_service__program__is_active=True,
                program_service__program__composite_program__is_active=True,
                program_service__service__is_active=True,
                program_service__service__service_category=ServiceCategory.THERAPY,
                sessions_used__lt=F("sessions_count"),
                program_service__service__center_assignments__center__pk=OuterRef("pk"),
                program_service__service__center_assignments__center__is_active=True,
                program_service__service__center_assignments__is_active=True,
                program_service__program__customer_profile__center_assignments__center=redemption_center,
                program_service__program__customer_profile__center_assignments__is_active=True,
            )
        return Center.objects.filter(
            redeemable_therapy_services=therapy_service,
        ).annotate(can_redeem=Exists(can_redeem_subquery)).order_by("-created_at", "-pk")

    def patch(self, request, *args, **kwargs):
        therapy_service = self.get_therapy_service()
        serializer = self.get_serializer(therapy_service, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        detail = self.get_update_success_message()
        return self.send_response(detail, serializer.data)

    def perform_update(self, serializer):
        serializer.save(therapy_service=serializer.instance)


class TherapyProgramServiceAvailableRedeemableCentersView(BaseListAPIView, TherapyProgramServiceViewMeta):
    serializer_class = TherapyServiceAvailableRedeemableCenterSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def get_queryset(self):
        therapy_service = self.get_therapy_service()
        program = therapy_service.program_service.program
        filter_kwargs = {}
        search = Q()
        search_parameter = self.request.query_params.get("search", "").strip()
        active_parameter = self.request.query_params.get("active")
        if active_parameter in ["0", "1"]:
            filter_kwargs["is_active"] = active_parameter == "1"
        if search_parameter:
            search = Q(name__icontains=search_parameter) | Q(code__istartswith=search_parameter)

        program_redeemable_centers = Center.objects.filter(
            pk=OuterRef("pk"),
            redeemable_programs=program,
        )
        if program.program_type == ProgramType.THERAPY:
            program_redeemable_centers = TherapyProgramService.objects.filter(
                pk=therapy_service.pk,
                is_discarded=False,
                program_service__program__therapy_program__is_discarded=False,
                program_service__program__redeemable_centers__pk=OuterRef("pk"),
            )
        if program.program_type == ProgramType.COMPOSITE:
            program_redeemable_centers = Center.objects.filter(
                pk=OuterRef("pk"), is_active=True,
                customer_assignments__customer_profile=program.customer_profile,
                customer_assignments__is_active=True,
                service_assignments__service=therapy_service.program_service.service,
                service_assignments__is_active=True,
            )
            if not program.composite_program.therapy_redemption_is_global:
                program_redeemable_centers = program_redeemable_centers.filter(
                    redeemable_programs=program,
                )
        therapy_service_centers = TherapyProgramService.objects.filter(
            pk=therapy_service.pk,
            redeemable_centers__pk=OuterRef("pk"),
        )
        home_center_assignments = CustomerCenterAssignment.objects.filter(
            customer_profile=program.customer_profile,
            center=OuterRef("pk"),
            is_primary=True,
        )
        return (
            Center.objects.annotate(
                can_redeem=Exists(program_redeemable_centers),
                exists=Exists(therapy_service_centers),
                is_home_center=Exists(home_center_assignments),
            )
            .filter(search, can_redeem=True, **filter_kwargs)
            .order_by("-is_home_center", "-exists", "-created_at", "-pk")
        )


class AssessmentProgramServiceDetailView(BaseRetrieveAPIView):
    serializer_class = AssessmentProgramServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        program_services = (
            ProgramService.objects.filter(
                service__service_category=ServiceCategory.ASSESSMENT,
            ).select_related(
                "service",
                "created_by",
                "cancelled_by",
            )
        )
        return program_services


class AssessmentProgramServiceProviders(
    BaseListAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = AssessmentServiceProviderSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        program_service = self.get_active_assessment_program_service()
        providers = Provider.objects.filter(
            is_active=True,
            products__is_active=True,
            products__service_assignments__service=program_service.service,
            products__service_assignments__is_active=True,
        ).distinct()
        return providers


class AssessmentProgramServiceProducts(
    BaseListAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = BaseProductSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        filter_kwargs = {}
        provider_code = self.request.query_params.get("provider", "").strip()
        if provider_code:
            filter_kwargs["provider__code"] = provider_code
        program_service = self.get_active_assessment_program_service()
        products = Product.objects.filter(
            is_active=True,
            provider__is_active=True,
            service_assignments__service=program_service.service,
            service_assignments__is_active=True,
            **filter_kwargs,
        ).select_related("provider")
        return products


class TherapyProgramServiceDetailView(BaseRetrieveUpdateAPIView):
    serializer_class = TherapyProgramServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def perform_update(self, serializer):
        serializer.save(updated_by=self.request.user)

    def get_queryset(self):
        filter_kwargs = {}
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.CUSTOMER:
            filter_kwargs["program__customer_profile__customer"] = self.request.user.customer
        return (
            ProgramService.objects.filter(
                service__service_category=ServiceCategory.THERAPY,
                **filter_kwargs,
            ).select_related(
                "service",
                "therapy_service",
                "therapy_service__discarded_by",
                "created_by",
                "cancelled_by",
                "program__customer_profile__customer__user",
                "program__therapy_program",
                "program__therapy_program__discarded_by",
            )
            .prefetch_related(
                Prefetch(
                    "therapy_service__redeemable_centers",
                    queryset=Center.objects.order_by("-created_at", "-pk"),
                    to_attr="redeemable_center_preview",
                ),
                Prefetch(
                    "service__center_assignments",
                    queryset=CenterServiceAssignment.objects.filter(
                        is_active=True,
                        center__redeemable_programs__program_services__pk=self.kwargs["pk"],
                    ).select_related("center").order_by("-created_at", "-pk"),
                    to_attr="active_center_assignments",
                ),
            )
        )


class BaseProgramServiceCancelView(
    BaseCreateAPIView,
    ProgramServiceCancelViewMeta,
):
    serializer_class = ProgramServiceCancelSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def perform_create(self, serializer):
        serializer.save(
            program_service=self.get_program_service(),
            cancelled_by=self.request.user,
        )


class AssessmentProgramServiceCancelView(BaseProgramServiceCancelView):
    service_category = ServiceCategory.ASSESSMENT


class TherapyProgramServiceCancelView(BaseProgramServiceCancelView):
    service_category = ServiceCategory.THERAPY
    program_service_filter_kwargs = {"therapy_service__isnull": False}

    def get_center(self):
        center_identifier = getattr(self.request, "center_id", None)
        if not center_identifier:
            self.raise_bad_request("X-Center-ID header is required.")
        centers = Center.objects.filter()
        return get_object_or_404(
            centers,
            "Center not found with this ID.",
            pk=center_identifier,
        )

    def perform_create(self, serializer):
        center = self.get_center()
        serializer.save(
            program_service=self.get_program_service(),
            cancelled_by=self.request.user,
            center=center,
        )


class TherapyProgramServiceDiscardView(BaseCreateAPIView):
    serializer_class = TherapyProgramServiceDiscardSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def get_queryset(self):
        center = self.get_center()
        return TherapyProgramService.objects.select_related(
            "program_service__program", "discarded_by",
        ).filter(
            program_service__program__center=center,
            program_service__program__program_type=ProgramType.THERAPY,
            program_service__service__service_category=ServiceCategory.THERAPY,
        )

    def get_center(self):
        center_identifier = getattr(self.request, "center_id", None)
        if not center_identifier:
            self.raise_bad_request("Center information not provided.")
        return get_object_or_404(
            Center.objects.all(), "Center not found with this ID.", pk=center_identifier,
        )

    def get_therapy_program_service(self):
        return get_object_or_404(
            self.get_queryset(),
            "Therapy program service not found.",
            pk=self.kwargs["pk"],
        )

    def perform_create(self, serializer):
        therapy_program_service = self.get_therapy_program_service()
        serializer.save(
            therapy_program_service=therapy_program_service,
            discarded_by=self.request.user,
        )


class ConsultationProgramServiceCancelView(BaseProgramServiceCancelView):
    service_category = ServiceCategory.CONSULTATION


class AssessmentServiceResultRequestView(
    BaseListCreateAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = AssessmentServiceResultRequestSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_serializer_class(self) -> type:
        if self.request.method == "POST":
            return AssessmentServiceResultRequestSerializer
        return AssessmentServiceResultRequestHistorySerializer

    def get_queryset(self) -> QuerySet[ResultRequest]:
        filter_kwargs = {}
        program_service = self.get_assessment_program_service()
        status = self.request.query_params.get('status', None)
        mode = self.request.query_params.get("mode", None)

        if mode and mode in RequestResultType:
            filter_kwargs["request_type"] = mode

        if status and status in ResultRequestStatus:
            filter_kwargs['status'] = status
        return (
            ResultRequest.objects.filter(
                program_service=program_service,
                **filter_kwargs,
            )
            .select_related(
                "product__provider",
                "created_by",
            )
            .prefetch_related("results", Prefetch(
                "files", queryset=ResultRequestFile.objects.order_by("-created_at"), to_attr="preview_files",
            ))
        )

    def perform_create(self, serializer):
        serializer.save(
            program_service=self.get_active_assessment_program_service(),
            created_by=self.request.user,
        )


class AssessmentServiceReportRequestView(
    BaseCreateAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = AssessmentServiceReportRequestSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]
    create_success_message = "Report request accepted."

    def perform_create(self, serializer):
        serializer.save(
            program_service=self.get_active_assessment_program_service(),
            created_by=self.request.user,
        )


class ResultRequestViewMeta(BaseGenericAPIView):
    def get_queryset(self) -> QuerySet[ResultRequest]:
        return (
            ResultRequest.objects.filter(
                program_service__service__service_category=(
                    ServiceCategory.ASSESSMENT
                ),
            )
            .select_related(
                "program_service__program",
                "program_service__service",
                "product__provider__api",
                "created_by",
            )
            .prefetch_related("results", Prefetch(
                "files", queryset=ResultRequestFile.objects.order_by("-created_at"), to_attr="preview_files",
            ))
        )

    def get_result_request(self) -> ResultRequest:
        return get_object_or_404(
            ResultRequestViewMeta.get_queryset(self),
            "Result request not found.",
            pk=self.kwargs["pk"],
        )


class ResultRequestDetailView(
    BaseRetrieveUpdateAPIView,
    ResultRequestViewMeta,
):
    serializer_class = AssessmentServiceResultRequestHistorySerializer
    permission_classes = [IsAdminUser | IsAssociateUser]


class ResultRequestConfirmOrderView(BaseCreateAPIView, ResultRequestViewMeta):
    serializer_class = OrderConfirmationSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]
    create_success_message = "Order confirmation accepted."

    def post(self, request: Request, *args, **kwargs) -> Response:
        result_request = self.get_result_request()
        if result_request.request_type != RequestResultType.ORDER or result_request.status == ResultRequestStatus.CANCELLED:
            raise ValidationError("Only non-cancelled order requests can be confirmed.")
        if result_request.is_submitted or result_request.status in [ResultRequestStatus.QUEUED,
                                                                    ResultRequestStatus.RUNNING]:
            return self.send_response(self.get_create_success_message(), status=202)
        if (
                result_request.status == ResultRequestStatus.FAILED
                and result_request.product.provider.callback != ProviderCallbackFunction.METFLUX
        ):
            raise ValidationError("A failed booking cannot be submitted again. Create another order.")
        if result_request.status not in [ResultRequestStatus.PENDING, ResultRequestStatus.FAILED]:
            raise ValidationError("This order cannot be confirmed.")
        serializer = self.get_serializer(result_request, data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response(self.get_create_success_message(), status=202)


class ResultRequestFilesView(BaseListAPIView, ResultRequestViewMeta):
    serializer_class = ResultRequestFileSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self) -> QuerySet[ResultRequestFile]:
        return ResultRequestFile.objects.filter(result_request=self.get_result_request()).order_by("-created_at")


class ResultRequestRefetchView(
    BaseCreateAPIView,
    ResultRequestViewMeta,
):
    serializer_class = ResultRequestRefetchSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def perform_create(self, serializer):
        serializer.save(result_request=self.get_result_request())


class ResultRequestCancelView(BaseCreateAPIView, ResultRequestViewMeta):
    serializer_class = ResultRequestCancelSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def perform_create(self, serializer) -> None:
        result_request = self.get_result_request()
        serializer.save(result_request=result_request)


class AssessmentProgramServiceResultsView(
    BaseListCreateAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = AssessmentServiceResultSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        filter_kwargs = {}
        product_identifier = self.request.query_params.get("product")
        if product_identifier:
            filter_kwargs["product__pk"] = product_identifier
        program_service = self.get_assessment_program_service()
        service_results = self.get_service_result_queryset().filter(
            program_service=program_service,
            **filter_kwargs,
        ).order_by('-created_at')
        return service_results

    def perform_create(self, serializer):
        program_service = self.get_assessment_program_service()
        serializer.save(
            program_service=program_service,
            created_by=self.request.user,
        )


class AssessmentProgramServiceDocumentsView(
    BaseListAPIView,
    AssessmentProgramServiceViewMeta,
):
    serializer_class = AssessmentServiceDocumentSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        filter_kwargs = {}
        result_identifier = self.request.query_params.get("result")
        document_type = self.request.query_params.get("document_type")
        document_category = self.request.query_params.get("document_category")
        module_category = self.request.query_params.get("module_category")
        search_query = self.request.query_params.get("search", "").strip()
        if result_identifier:
            filter_kwargs["result__pk"] = result_identifier
        if document_type:
            filter_kwargs["result__document_type"] = document_type
        if document_category:
            filter_kwargs["document_category"] = document_category
        if module_category:
            filter_kwargs["result__document_type__in"] = (
                get_module_category_document_types(module_category)
            )
        if search_query:
            filter_kwargs["filename__icontains"] = search_query
        program_service = self.get_assessment_program_service()
        service_documents = self.get_service_document_queryset().filter(
            result__program_service=program_service,
            **filter_kwargs,
        )
        return service_documents


class ServiceResultDetailView(
    BaseRetrieveDestroyAPIView,
    UpdateModelMixin,
):
    serializer_class = AssessmentServiceResultSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        service_results = (
            ServiceResult.objects.filter(
                program_service__service__service_category=(
                    ServiceCategory.ASSESSMENT
                ),
            )
            .select_related(
                "program_service",
                "program_service__service",
                "product",
                "product__provider",
                "created_by",
            )
        )
        return service_results

    def patch(self, request, *args, **kwargs):
        response = self.partial_update(request, *args, **kwargs)
        context = response_format(
            self.get_update_success_message(),
            response.data,
        )
        return Response(context, response.status_code)

    def perform_destroy(self, instance):
        delete_service_result(instance)


class ServiceResultDocumentsView(BaseListCreateAPIView):
    serializer_class = AssessmentServiceDocumentSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_service_result(self):
        service_results = ServiceResult.objects.filter(
            program_service__service__service_category=(
                ServiceCategory.ASSESSMENT
            ),
        ).select_related(
            "program_service",
            "program_service__service",
        )
        return get_object_or_404(
            service_results,
            "Assessment service result not found.",
            pk=self.kwargs["pk"],
        )

    def get_queryset(self):
        filter_kwargs = {}
        document_type = self.request.query_params.get("document_type")
        document_category = self.request.query_params.get("document_category")
        search_query = self.request.query_params.get("search", "").strip()
        if document_type:
            filter_kwargs["result__document_type"] = document_type
        if document_category:
            filter_kwargs["document_category"] = document_category
        if search_query:
            filter_kwargs["filename__icontains"] = search_query
        service_result = self.get_service_result()
        service_documents = ServiceDocument.objects.filter(
            result=service_result,
            result__program_service__service__service_category=(
                ServiceCategory.ASSESSMENT
            ),
            **filter_kwargs,
        ).select_related(
            "result",
            "result__program_service",
        )
        return service_documents

    def perform_create(self, serializer):
        service_result = self.get_service_result()
        serializer.save(result=service_result)


class ServiceDocumentDeleteView(BaseDestroyAPIView):
    serializer_class = AssessmentServiceDocumentSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        service_documents = ServiceDocument.objects.filter(
            result__program_service__service__service_category=(
                ServiceCategory.ASSESSMENT
            ),
        ).select_related(
            "result",
            "result__program_service",
        )
        return service_documents

    def perform_destroy(self, instance):
        delete_service_document(instance)
