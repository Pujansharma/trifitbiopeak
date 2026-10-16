from django.db.models import (
    BooleanField,
    Count,
    ExpressionWrapper,
    F,
    Prefetch,
    Q,
    Sum,
)
from django.db.models.functions import Coalesce, TruncMonth
from django.utils import timezone

from accounts.centers.models import Center
from accounts.customers.models import CustomerProfile
from accounts.customers.programs.serializers import (
    CustomerCompositeProgramSerializer,
    CustomerCompositeProgramServiceFilterSerializer,
    CustomerCompositeProgramServiceListSerializer,
    CustomerTherapyProgramSerializer,
    CustomerTherapyProgramServiceSerializer,
    CustomerDocumentExportSerializer,
    CustomerMetsightsResultSerializer,
    CustomerProgramSummarySerializer,
)
from accounts.customers.views import CustomerDocumentsViewMeta, CustomerProfileMeta, CustomerProfileAccessViewMeta
from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from accounts.utils.permissions import IsAdminUser, IsAssociateUser, IsCustomerUser
from appointments.models import Appointment
from appointments.utils.redemption import OPEN_APPOINTMENT_STATUSES
from core.utils.exceptions import get_object_or_404
from core.utils.permissions import ReadOnly
from core.utils.views.main import (
    BaseGenericAPIView,
    BaseListAPIView,
    BaseListCreateAPIView,
    BaseRetrieveAPIView,
)
from external.permissions import ExternalAPIKeyPermission
from external.serializers import CustomerProfileSummarySerializer
from external.views import ExternalUserProgramSummaryView
from programs.composites.views import CompositeProgramViewMeta
from programs.models import Program, ProgramService, TherapyProgram
from programs.program_services.serializers import AssessmentProgramServiceSerializer
from programs.serializers import BaseProgramSerializer
from programs.services.models import CenterServiceAssignment, ServiceResult
from programs.services.utils.constants import ServiceCategory, ServiceDocumentType
from programs.models import ProgramService, TherapyProgram, TherapyProgramService
from programs.services.models import CenterServiceAssignment
from programs.services.utils.constants import ServiceCategory
from programs.utils.constants import ProgramType
from webhooks.metsights.tasks import send_reports_export_email


class CustomerProgramServicesView(BaseListAPIView, CustomerProfileAccessViewMeta):
    serializer_class = AssessmentProgramServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | IsCustomerUser | (ExternalAPIKeyPermission & ReadOnly)]

    def get_queryset(self):
        customer_profile = self.get_customer_profile()
        filter_kwargs = {"program__customer_profile": customer_profile}
        service_category = self.request.query_params.get("type")
        if service_category is not None:
            if service_category not in ServiceCategory.values:
                self.raise_bad_request("Invalid type. Use assessment, therapy, or consultation.")
            filter_kwargs["service__service_category"] = service_category
        center_conditions = Q()
        account_type = get_user_account_type(self.request.user)
        if account_type in {UserType.ADMIN, UserType.ASSOCIATE}:
            center_identifier = self.request.headers.get("X-Center-ID") or self.request.query_params.get("center_id")
            center_conditions = Q(program__center__pk=center_identifier) | Q(
                program__redeemable_centers__pk=center_identifier)
        return ProgramService.objects.select_related(
            "service", "created_by", "cancelled_by",
        ).prefetch_related(
            Prefetch(
                "service__center_assignments",
                queryset=CenterServiceAssignment.objects.filter(is_active=True).select_related("center"),
                to_attr="active_center_assignments",
            ),
        ).filter(center_conditions, **filter_kwargs).order_by("-created_at", "-pk").distinct()


class CustomerProgramViewMeta(BaseGenericAPIView):
    @classmethod
    def get_therapy_program_queryset(cls):
        service_preview = ProgramService.objects.select_related(
            "service",
            "created_by",
            "therapy_service",
            "program__customer_profile__customer__user",
            "program__therapy_program",
        ).prefetch_related(
            Prefetch(
                "service__center_assignments",
                queryset=CenterServiceAssignment.objects.filter(
                    is_active=True,
                ).select_related("center"),
                to_attr="active_center_assignments",
            ),
        )
        return (
            TherapyProgram.objects.select_related(
                "program",
                "program__created_by",
            )
            .prefetch_related(
                Prefetch(
                    "program__program_services",
                    queryset=service_preview,
                    to_attr="service_preview",
                ),
                "program__redeemable_centers",
            )
        )

    def get_customer_profile(self) -> CustomerProfile:
        filter_kwargs = {}
        user = self.request.user
        account_type = get_user_account_type(user)
        if account_type == UserType.CUSTOMER:
            filter_kwargs["customer"] = user.customer
        customer_profiles = CustomerProfile.objects.filter(**filter_kwargs)
        return get_object_or_404(
            customer_profiles,
            "Customer profile with this ID not found.",
            pk=self.kwargs["pk"],
        )


class CustomerCompositeProgramViewMeta(CompositeProgramViewMeta):
    def get_center(self):
        center_identifier = self.request.headers.get("X-Center-ID")
        filter_kwargs = {}
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.ASSOCIATE:
            filter_kwargs["associate_assignments__associate"] = self.request.user.associate
            filter_kwargs["associate_assignments__is_active"] = True
        centers = Center.objects.filter(is_active=True, **filter_kwargs).distinct()
        return get_object_or_404(
            centers,
            "No valid center found with the given ID.",
            pk=center_identifier,
        )

    def get_customer_profile(self, center: Center):
        filter_kwargs = {
            "is_active": True,
            "center_assignments__center": center,
            "center_assignments__is_active": True,
        }
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.ASSOCIATE:
            filter_kwargs.update(
                {
                    "associate_assignments__associate": self.request.user.associate,
                    "associate_assignments__center": center,
                    "associate_assignments__is_active": True,
                }
            )
        customer_profiles = CustomerProfile.objects.filter(
            **filter_kwargs
        ).distinct()
        return get_object_or_404(
            customer_profiles,
            "Customer profile with this ID not found.",
            pk=self.kwargs["pk"],
        )


class CustomerTherapyProgramsView(
    BaseListCreateAPIView,
    CustomerProgramViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]
    serializer_class = CustomerTherapyProgramSerializer

    def get_queryset(self):
        filter_kwargs = {}
        active_query = self.request.query_params.get("active")
        complete_query = self.request.query_params.get("complete")
        expired_query = self.request.query_params.get("expired")
        customer_profile = self.get_customer_profile()

        if active_query in {"0", "1"}:
            filter_kwargs["is_active"] = bool(int(active_query))
        if complete_query in {"0", "1"}:
            filter_kwargs["is_complete"] = bool(int(complete_query))

        expired_filters = {
            "1": {"program__expires_at__lt": timezone.localdate()},
            "0": {"program__expires_at__gte": timezone.localdate()},
        }
        if expired_query in expired_filters:
            filter_kwargs.update(expired_filters[expired_query])

        return (
            self.get_therapy_program_queryset()
            .annotate(
                is_complete=ExpressionWrapper(
                    Q(sessions_count=F("sessions_used") + F("sessions_cancelled")),
                    output_field=BooleanField(),
                )
            )
            .filter(
                program__customer_profile=customer_profile,
                **filter_kwargs,
            )
        )

    def perform_create(
            self,
            serializer,
    ) -> None:
        customer_profile = self.get_customer_profile()
        serializer.save(
            customer_profile=customer_profile,
            created_by=self.request.user,
        )


class CustomerTherapyProgramServicesView(
    BaseListAPIView,
    CustomerProgramViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]
    serializer_class = CustomerTherapyProgramServiceSerializer

    def get_therapy_program(self) -> TherapyProgram:
        return get_object_or_404(
            TherapyProgram.objects.filter(
                program__customer_profile=self.get_customer_profile(),
            ),
            "Therapy program not found with this ID",
            pk=self.kwargs["program_pk"],
        )

    def get_queryset(self):
        therapy_program = self.get_therapy_program()
        return (
            TherapyProgramService.objects.filter(
                program_service__program__therapy_program=therapy_program,
            )
            .select_related("program_service__service")
            .defer("program_service__data")
            .prefetch_related(
                Prefetch(
                    "program_service__service__center_assignments",
                    queryset=CenterServiceAssignment.objects.filter(
                        center__redeemable_programs__therapy_program=therapy_program,
                        is_active=True,
                    ).select_related("center"),
                ),
                Prefetch(
                    "program_service__appointments",
                    queryset=Appointment.objects.filter(
                        status__in=OPEN_APPOINTMENT_STATUSES,
                    ).select_related("center", "room"),
                    to_attr="open_appointments",
                ),
            )
            .order_by("-created_at")
        )


class CustomerCompositeProgramsView(
    BaseListCreateAPIView,
    CustomerCompositeProgramViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = CustomerCompositeProgramSerializer

    def get_queryset(self):
        filter_kwargs = {}
        search = Q()
        search_params = self.request.query_params.get('search', "")
        search_params = search_params.strip()
        active_query = self.request.query_params.get("active")
        expired_query = self.request.query_params.get("expired")
        service_category_query = self.request.query_params.get('category')

        if search_params:
            search |= Q(composite_template__code__icontains=search_params)
            search |= Q(composite_template__name__icontains=search_params)
            search |= Q(composite_template__name__istartswith=search_params)
            search |= Q(program__uid__istartswith=search_params)
            search |= Q(program__uid__iexact=search_params)

        if active_query in {"0", "1"}:
            filter_kwargs["program__is_active"] = bool(int(active_query))

        if service_category_query:
            # program__program_services__service__service_category
            # pass
            filter_kwargs[
                'program__program_services__service__service_category'
            ] = service_category_query

        expired_filters = {
            "1": {"program__expires_at__lt": timezone.localdate()},
            "0": {"program__expires_at__gte": timezone.localdate()},
        }
        if expired_query and expired_query in expired_filters:
            filter_kwargs.update(expired_filters[expired_query])

        center = self.get_center()
        customer_profile = self.get_customer_profile(center)
        return self.get_composite_program_queryset(center.pk).filter(
            search, program__customer_profile=customer_profile,
            **filter_kwargs,
        ).distinct()

    def perform_create(
            self,
            serializer,
    ):
        center = self.get_center()
        serializer.save(
            customer_profile=self.get_customer_profile(center),
            center=center,
            created_by=self.request.user,
        )


class CustomerCompositeProgramServicesView(
    BaseListAPIView,
    CustomerCompositeProgramViewMeta,
):
    permission_classes = [IsAdminUser | IsAssociateUser]
    serializer_class = CustomerCompositeProgramServiceListSerializer

    def get_filters(self):
        serializer = CustomerCompositeProgramServiceFilterSerializer(
            data=self.request.query_params
        )
        serializer.is_valid(raise_exception=True)
        return serializer.validated_data

    def get_queryset(self):
        center = self.get_center()
        customer_profile = self.get_customer_profile(center)
        filters = self.get_filters()
        filter_kwargs = {
            "program__program_type": ProgramType.COMPOSITE,
            "program__customer_profile": customer_profile,
            "service__service_category__in": [
                ServiceCategory.ASSESSMENT,
                ServiceCategory.THERAPY,
            ],
        }

        service_category = filters.get("service_category")
        assignment_type = filters.get("assignment_type")
        composite_program_identifier = filters.get("composite_program")
        search = filters.get("search", "")
        search = search.strip()
        active = filters.get("active")

        if service_category:
            filter_kwargs["service__service_category"] = service_category
        if assignment_type:
            filter_kwargs["assignment_type"] = assignment_type
        if composite_program_identifier:
            filter_kwargs[
                "program__composite_program__pk"
            ] = composite_program_identifier
        if search:
            filter_kwargs["service__name__icontains"] = search
        if active is not None:
            filter_kwargs["is_active"] = bool(int(active))

        return (
            self.get_composite_program_service_queryset(center.pk)
            .select_related(
                "program",
                "program__composite_program",
                "program__composite_program__composite_template",
            )
            .filter(
                Q(program__center=center)
                | Q(program__redeemable_centers=center),
                **filter_kwargs,
            )
            .order_by("-created_at")
            .distinct()
        )


class CustomerDocumentTimelinesView(CustomerDocumentsViewMeta):
    permission_classes = [IsCustomerUser]

    def get(self, request, *args, **kwargs):
        months = self.get_queryset().exclude(
            result__sample_collection_date__isnull=True,
        ).annotate(
            collection_month=TruncMonth("result__sample_collection_date"),
        ).values_list("collection_month", flat=True).order_by("-collection_month").distinct()
        data = [{"month": month.month, "year": month.year} for month in months.iterator()]
        return self.send_response("Document timelines fetched.", data=data)


class CustomerMetsightsResultsView(BaseListAPIView, CustomerDocumentsViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = CustomerMetsightsResultSerializer

    def get_queryset(self):
        filters = self.get_collection_date_filters()
        customer_profile = self.get_customer_profile()
        filter_kwargs = {}
        for parameter in ("month", "year"):
            if parameter in filters:
                filter_kwargs[f"sample_collection_date__{parameter}"] = filters[parameter]
        return ServiceResult.objects.select_related(
            "product", "program_service__service", "program_service__program",
            "program_service__program__composite_program__composite_template",
        ).filter(
            is_active=True,
            program_service__program__customer_profile=customer_profile,
            document_type=ServiceDocumentType.METSIGHTS_PP,
            **filter_kwargs,
        ).order_by("-sample_collection_date", "-created_at", "-pk")


class CustomerDocumentExportView(CustomerDocumentsViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = CustomerDocumentExportSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        documents = self.get_queryset()
        documents_exist = documents.exists()
        if not documents_exist:
            self.raise_bad_request("No documents match the supplied filters.")
        customer_profile = self.get_customer_profile()
        first_name = customer_profile.first_name
        first_name = first_name or ""
        files = (
            {
                "file_url": document.file.url,
                "filename": document.filename,
                "document_id": str(document.pk),
            }
            for document in documents.iterator(chunk_size=100) if document.file
        )
        documents_count = send_reports_export_email(
            serializer.validated_data["email"],
            first_name,
            files,
            as_zip=True,
        )
        if not documents_count:
            self.raise_bad_request("No matching documents could be downloaded.")
        return self.send_response("Reports export request received.")


class CustomerProgramsView(BaseListAPIView, CustomerProfileMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = BaseProgramSerializer

    def get_queryset(self):
        filter_kwargs = {}
        customer_profile = self.get_customer_profile()
        active = self.request.query_params.get("active")
        program_type = self.request.query_params.get("program_type")
        expired = self.request.query_params.get("expired")
        if active in {"0", "1"}:
            filter_kwargs["is_active"] = bool(int(active))
        if program_type in ProgramType.values:
            filter_kwargs["program_type"] = program_type
        expired_filters = {
            "1": {"expires_at__lt": timezone.localdate()},
            "0": {"expires_at__gte": timezone.localdate()},
        }
        expired_filter_kwargs = expired_filters.get(expired, {})
        filter_kwargs.update(expired_filter_kwargs)
        return Program.objects.select_related("customer_profile__customer__user", "therapy_program").filter(
            customer_profile=customer_profile,
            **filter_kwargs,
        ).order_by("-created_at", "-pk")


class CustomerProgramSummaryViewMeta(CustomerProfileMeta):
    def get_program_summary(self, customer_profile: CustomerProfile, program_type: str | None) -> dict:
        program_filters = {}
        service_filters = {}
        if program_type is not None:
            program_filters["program_type"] = program_type
            service_filters["program__program_type"] = program_type
        summary = Program.objects.filter(
            customer_profile=customer_profile,
            **program_filters,
        ).aggregate(
            programs_count=Count("pk"),
            programs_active=Count("pk", filter=Q(is_active=True)),
            programs_inactive=Count("pk", filter=Q(is_active=False)),
            programs_expired=Count("pk", filter=Q(expires_at__lt=timezone.localdate())),
        )
        service_summary = ProgramService.objects.filter(
            program__customer_profile=customer_profile,
            **service_filters,
        ).aggregate(
            services_count=Count("pk"),
            services_active=Count("pk", filter=Q(is_active=True)),
            services_inactive=Count("pk", filter=Q(is_active=False)),
            results_count=Coalesce(Sum("results_count"), 0),
            documents_count=Coalesce(Sum("documents_count"), 0),
            reports_count=Coalesce(Sum("reports_count"), 0),
            raw_data_count=Coalesce(Sum("raw_data_count"), 0),
            fetch_count=Coalesce(Sum("fetch_count"), 0),
            fetch_results_count=Coalesce(Sum("fetch_results_count"), 0),
            fetch_documents_count=Coalesce(Sum("fetch_documents_count"), 0),
            fetch_pending_count=Coalesce(Sum("fetch_pending_count"), 0),
        )
        summary.update(service_summary)
        summary["id"] = customer_profile.pk
        summary["first_name"] = customer_profile.first_name
        summary["last_name"] = customer_profile.last_name
        return summary


class CustomerProgramTypeSummaryView(BaseRetrieveAPIView, CustomerProgramSummaryViewMeta):
    permission_classes = [IsCustomerUser]
    serializer_class = CustomerProgramSummarySerializer
    program_type = None

    def get_object(self):
        customer_profile = self.get_customer_profile()
        return self.get_program_summary(customer_profile, self.program_type)


class CustomerAssessmentProgramSummaryView(CustomerProgramTypeSummaryView):
    program_type = ProgramType.ASSESSMENT


class CustomerConsultationProgramSummaryView(CustomerProgramTypeSummaryView):
    program_type = ProgramType.CONSULTATION


class CustomerCompositeProgramSummaryView(CustomerProgramTypeSummaryView):
    program_type = ProgramType.COMPOSITE


class CustomerTherapyProgramSummaryView(ExternalUserProgramSummaryView, CustomerProgramSummaryViewMeta):
    permission_classes = [IsCustomerUser]

    def get_customer_profile(self):
        return CustomerProfileMeta.get_customer_profile(self)


class CustomerProgramsSummaryView(CustomerTherapyProgramSummaryView):
    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        totals = self.get_program_summary(customer_profile, None)
        type_counts = Program.objects.filter(customer_profile=customer_profile).values("program_type").annotate(
            count=Count("pk"),
        )
        totals["programs_by_type"] = {program_type: 0 for program_type in ProgramType.values}
        totals["programs_by_type"].update({item["program_type"]: item["count"] for item in type_counts})
        therapy_summary = self.get_object()
        serializer_context = self.get_serializer_context()
        serializer = CustomerProfileSummarySerializer(therapy_summary, context=serializer_context)
        totals["therapy"] = serializer.data
        totals["assessment"] = self.get_program_summary(customer_profile, ProgramType.ASSESSMENT)
        totals["consultation"] = self.get_program_summary(customer_profile, ProgramType.CONSULTATION)
        totals["composite"] = self.get_program_summary(customer_profile, ProgramType.COMPOSITE)
        return self.send_response("Program summary retrieved.", data=totals)
