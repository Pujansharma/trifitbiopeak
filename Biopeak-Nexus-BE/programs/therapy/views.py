from django.db.models import F, Prefetch, OuterRef, Exists, Q
from django.utils import timezone

from accounts.centers.models import Center
from accounts.centers.serializers import MinimumCenterSerializer
from accounts.customers.models import CustomerCenterAssignment
from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from accounts.utils.permissions import (
    BaseAssociateRBACPermission,
    IsAdminUser,
    IsAssociateUser,
    IsCustomerUser,
)
from appointments.models import Appointment, AppointmentAssociate
from appointments.utils.redemption import OPEN_APPOINTMENT_STATUSES
from core.utils.exceptions import get_object_or_404
from core.utils.permissions import ReadOnly
from core.utils.views.main import (
    BaseListAPIView,
    BaseRetrieveUpdateAPIView,
    BaseCreateAPIView,
    BaseGenericAPIView,
)
from programs.models import ProgramService, TherapyProgram, TherapyProgramService
from programs.serializers import (
    BaseProgramServiceSerializer,
    ProgramAvailableRedeemableCenterSerializer,
)
from programs.services.models import CenterServiceAssignment, Service
from programs.services.utils.constants import ServiceCategory
from programs.therapy.serializers import (
    TherapyProgramAvailableServiceSerializer,
    TherapyProgramDetailSerializer,
    TherapyProgramCancelSerializer,
    TherapyProgramDiscardSerializer,
    TherapyProgramRedeemSerializer,
    TherapyProgramServiceSerializer,
)
from programs.utils.constants import ProgramType


class TherapyProgramServicesView(BaseListAPIView):
    serializer_class = TherapyProgramServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        code_query_param = self.request.query_params.get("code", None)
        qs = TherapyProgramService.objects.filter(
            redeem_code__iexact=code_query_param
        ).select_related(
            "discarded_by",
            "program_service",
            "program_service__cancelled_by",
            "program_service__created_by",
            "program_service__program__customer_profile",
            "program_service__program__therapy_program__discarded_by",
            "program_service__service",
        ).prefetch_related("redeemable_centers")
        return qs


class TherapyProgramServiceViewMeta(BaseGenericAPIView):
    def get_program_service_queryset(self):
        center_filters = {}
        center_identifier = self.request.headers.get("X-Center-ID")
        if center_identifier:
            center_filters["center__pk"] = center_identifier
        can_redeem_subquery = CenterServiceAssignment.objects.filter(
            Q(center__redeemable_therapy_services__program_service__program__expires_at__isnull=True)
            | Q(center__redeemable_therapy_services__program_service__program__expires_at__gte=timezone.localdate()),
            service=OuterRef("service"),
            is_active=True,
            center__redeemable_programs__pk=OuterRef("program"),
            center__redeemable_therapy_services__program_service__pk=OuterRef("pk"),
            center__redeemable_therapy_services__is_active=True,
            center__redeemable_therapy_services__is_discarded=False,
            center__redeemable_therapy_services__program_service__is_active=True,
            center__redeemable_therapy_services__program_service__program__is_active=True,
            center__redeemable_therapy_services__program_service__program__therapy_program__is_active=True,
            center__redeemable_therapy_services__program_service__program__therapy_program__is_discarded=False,
            center__redeemable_therapy_services__sessions_used__lt=F(
                "center__redeemable_therapy_services__sessions_count"),
            **center_filters,
        )
        return (
            ProgramService.objects.annotate(can_redeem=Exists(can_redeem_subquery))
            .prefetch_related(
                Prefetch(
                    "therapy_service__redeemable_centers",
                    queryset=Center.objects.all(),
                    to_attr="redeemable_center_preview",
                ),
            )
        )


class TherapyProgramViewMeta(TherapyProgramServiceViewMeta):
    filter_kwargs = {}

    def get_therapy_program_queryset(self):
        filter_kwargs = {"program__program_type": ProgramType.THERAPY}
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.CUSTOMER:
            filter_kwargs["program__customer_profile__customer"] = self.request.user.customer
        return (
            TherapyProgram.objects.filter(**filter_kwargs)
            .select_related(
                "discarded_by",
                "program",
                "program__center",
                "program__created_by",
                "program__customer_profile__customer__user",
            )
            .prefetch_related(
                Prefetch(
                    "program__program_services",
                    queryset=self.get_program_service_queryset().select_related(
                        "program", "service", "created_by", "cancelled_by", "therapy_service",
                        "therapy_service__discarded_by", "program__therapy_program__discarded_by",
                    ).order_by("-created_at", "-pk"),
                    to_attr="service_preview",
                ),
                Prefetch(
                    "program__redeemable_centers",
                    queryset=Center.objects.all(),
                    to_attr="redeemable_center_preview",
                ),
                Prefetch(
                    "program__customer_profile__center_assignments",
                    queryset=CustomerCenterAssignment.objects.filter(
                        is_primary=True
                    ).select_related("center"),
                    to_attr="primary_center_assignments",
                ),
            )
        )

    def get_therapy_program(self):
        qs = self.get_therapy_program_queryset()
        return get_object_or_404(
            qs,
            "Therapy program not found.",
            pk=self.kwargs["pk"],
        )


class TherapyProgramDetailView(BaseRetrieveUpdateAPIView, TherapyProgramViewMeta):
    serializer_class = TherapyProgramDetailSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def get_queryset(self):
        return self.get_therapy_program_queryset()


class TherapyProgramRedeemableCentersView(BaseListAPIView, TherapyProgramViewMeta):
    serializer_class = MinimumCenterSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def get_queryset(self):
        therapy_program = self.get_therapy_program()
        return Center.objects.filter(
            redeemable_programs__therapy_program__pk=therapy_program.pk,
        ).order_by("-created_at", "-pk")


class TherapyProgramAvailableRedeemableCentersView(BaseListAPIView, TherapyProgramViewMeta):
    serializer_class = ProgramAvailableRedeemableCenterSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def get_therapy_program_queryset(self):
        """Preserve ownership scope without loading unrelated detail previews."""
        return (
            super().get_therapy_program_queryset()
            .select_related(None)
            .select_related("program__customer_profile")
            .prefetch_related(None)
        )

    def get_queryset(self):
        therapy_program = self.get_therapy_program()
        program = therapy_program.program
        filter_kwargs = {}
        search = Q()
        search_parameter = self.request.query_params.get("search", "").strip()
        active_parameter = self.request.query_params.get("active")
        if active_parameter in ["0", "1"]:
            filter_kwargs["is_active"] = active_parameter == "1"
        if search_parameter:
            search = Q(name__icontains=search_parameter) | Q(code__istartswith=search_parameter)

        customer_center_assignments = CustomerCenterAssignment.objects.filter(
            customer_profile=program.customer_profile,
            center=OuterRef("pk"),
        )
        redeemable_centers = Center.objects.filter(
            pk=OuterRef("pk"),
            redeemable_programs=program,
        )
        return (
            Center.objects.filter(Exists(customer_center_assignments), search, **filter_kwargs)
            .annotate(
                exists=Exists(redeemable_centers),
                is_home_center=Exists(customer_center_assignments.filter(is_primary=True)),
            )
            .order_by("-is_home_center", "-exists", "-created_at", "-pk")
        )


class TherapyProgramAvailableServicesView(BaseListAPIView, TherapyProgramViewMeta):
    serializer_class = TherapyProgramAvailableServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_queryset(self):
        therapy_program = self.get_therapy_program()
        program = therapy_program.program
        filter_kwargs = {"service_category": ServiceCategory.THERAPY}
        search = Q()
        search_parameter = self.request.query_params.get("search", "").strip()
        active_parameter = self.request.query_params.get("active")
        exists_parameter = self.request.query_params.get("exists")
        if search_parameter:
            search = Q(name__icontains=search_parameter)
        if active_parameter in ["0", "1"]:
            filter_kwargs["is_active"] = active_parameter == "1"
        if exists_parameter in ["0", "1"]:
            filter_kwargs["exists"] = exists_parameter == "1"

        center_assignments = CenterServiceAssignment.objects.filter(
            service=OuterRef("pk"),
            center__redeemable_programs=program,
        )
        program_services = ProgramService.objects.filter(service=OuterRef("pk"))
        return (
            Service.objects.annotate(
                exists=Exists(program_services.filter(program=program)),
                is_locked=Exists(program_services),
            )
            .filter(
                Q(is_global=True) | Exists(center_assignments),
                search,
                **filter_kwargs,
            )
            .prefetch_related(
                Prefetch(
                    "center_assignments",
                    queryset=CenterServiceAssignment.objects.filter(
                        center__redeemable_programs=program,
                        center__is_active=True,
                    ).select_related("center"),
                ),
            )
            .select_related("created_by", "care_template")
            .order_by("-created_at")
        )


class TherapyProgramServicesListView(BaseListAPIView, TherapyProgramServiceViewMeta):
    serializer_class = BaseProgramServiceSerializer
    permission_classes = [IsAdminUser | IsAssociateUser | (IsCustomerUser & ReadOnly)]

    def get_queryset(self):
        filter_kwargs = {}
        discarded_query = self.request.query_params.get("discarded")
        if discarded_query in ["0", "1"]:
            filter_kwargs["therapy_service__is_discarded"] = bool(int(discarded_query))
        account_type = get_user_account_type(self.request.user)
        if account_type == UserType.CUSTOMER:
            filter_kwargs["program__customer_profile__customer"] = self.request.user.customer
        return (
            self.get_program_service_queryset().filter(
                program__therapy_program__pk=self.kwargs["pk"],
                **filter_kwargs,
            )
            .select_related(
                "cancelled_by",
                "created_by",
                "service",
                "therapy_service",
                "therapy_service__discarded_by",
                "program__customer_profile__customer__user",
                "program__therapy_program",
                "program__therapy_program__discarded_by",
            )
            .prefetch_related(
                Prefetch(
                    "service__center_assignments",
                    queryset=CenterServiceAssignment.objects.filter(
                        is_active=True,
                        center__redeemable_programs__therapy_program__pk=self.kwargs["pk"],
                    ).select_related("center").order_by("-created_at", "-pk"),
                    to_attr="active_center_assignments",
                ),
                Prefetch(
                    "appointments",
                    queryset=Appointment.objects.filter(
                        status__in=OPEN_APPOINTMENT_STATUSES,
                    )
                    .select_related("center", "care_team", "room", "equipment")
                    .prefetch_related(
                        Prefetch(
                            "associate_links",
                            queryset=AppointmentAssociate.objects.select_related(
                                "associate__user", "role"
                            ),
                        ),
                    ),
                    to_attr="open_appointments",
                ),
            )
            .order_by("-created_at")
        )


class TherapyProgramDiscardView(BaseCreateAPIView):
    serializer_class = TherapyProgramDiscardSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def get_queryset(self):
        center = self.get_center()
        return TherapyProgram.objects.select_related("program", "discarded_by").filter(
            program__center=center,
            program__program_type=ProgramType.THERAPY,
        )

    def get_center(self):
        center_identifier = self.request.headers.get("X-Center-ID")
        return get_object_or_404(
            Center.objects.all(), "Invalid center ID provided", pk=center_identifier,
        )

    def get_therapy_program(self):
        return get_object_or_404(
            self.get_queryset(),
            "Therapy program not found with this ID",
            pk=self.kwargs["pk"],
        )

    def perform_create(self, serializer):
        therapy_program = self.get_therapy_program()
        serializer.save(therapy_program=therapy_program, discarded_by=self.request.user)


class TherapyProgramCancelView(BaseCreateAPIView):
    serializer_class = TherapyProgramCancelSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_therapy_program(self):
        # filter_kwargs = {}
        # user = self.request.user
        # account_type = get_user_account_type(user)
        # if account_type == UserType.ASSOCIATE:
        #     associate = getattr(user, 'associate')
        #
        qs = TherapyProgram.objects.select_related().prefetch_related().filter()
        return get_object_or_404(
            qs, "Therapy program not found with this ID", pk=self.kwargs["pk"]
        )

    def get_center(self):
        center_id = self.request.headers.get("x-center-id")
        qs = Center.objects.filter()
        return get_object_or_404(qs, "Invalid center ID provided", pk=center_id)

    def perform_create(self, serializer):
        serializer.save(
            therapy_program=self.get_therapy_program(),
            cancelled_by=self.request.user,
            center=self.get_center(),
        )


class TherapyProgramRedeemView(BaseCreateAPIView):
    serializer_class = TherapyProgramRedeemSerializer
    permission_classes = [IsAdminUser | IsAssociateUser]

    def get_therapy_program(self):
        qs = TherapyProgram.objects.select_related("program").filter()
        return get_object_or_404(
            qs, "Therapy program not found with this ID", pk=self.kwargs["pk"]
        )

    def perform_create(self, serializer):
        serializer.save(
            therapy_program=self.get_therapy_program(),
            redeemed_by=self.request.user,
        )
