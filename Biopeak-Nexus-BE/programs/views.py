from django.db.models import Q, QuerySet

from accounts.centers.models import Center
from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from accounts.utils.permissions import BaseAssociateRBACPermission, IsAdminUser
from core.utils.exceptions import get_object_or_404
from core.utils.views.main import BaseCreateAPIView, BaseGenericAPIView, BaseListAPIView
from programs.models import Program, ProgramAuditLog, ProgramPaymentHistory
from programs.serializers import ProgramAuditLogSerializer, ProgramPaymentHistorySerializer
from programs.utils.constants import ProgramType


class ProgramAuditViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_program(self) -> Program:
        programs = Program.objects.filter(**self.filter_kwargs)
        if get_user_account_type(self.request.user) == UserType.ASSOCIATE:
            centers = Center.objects.filter(
                is_active=True,
                associate_assignments__associate=self.request.user.associate,
                associate_assignments__is_active=True,
            )
            programs = programs.filter(
                Q(center__in=centers) | Q(redeemable_centers__in=centers)
            ).distinct()
        return get_object_or_404(
            programs, "Program not found.", pk=self.kwargs["pk"],
        )


class ProgramAuditHistoryView(BaseListAPIView, ProgramAuditViewMeta):
    serializer_class = ProgramAuditLogSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def get_queryset(self) -> QuerySet[ProgramAuditLog]:
        return ProgramAuditLog.objects.filter(
            program=self.get_program(),
        ).select_related("created_by").order_by("-created_at", "-pk")


class ProgramPaymentViewMeta(BaseGenericAPIView):
    filter_kwargs = {}

    def get_program(self):
        programs = Program.objects.filter(**self.filter_kwargs)
        if get_user_account_type(self.request.user) == UserType.ASSOCIATE:
            centers = Center.objects.filter(
                is_active=True,
                associate_assignments__associate=self.request.user.associate,
                associate_assignments__is_active=True,
            )
            programs = programs.filter(
                Q(center__in=centers) | Q(redeemable_centers__in=centers)
            ).distinct()
        return get_object_or_404(
            programs, "Program not found.", pk=self.kwargs["pk"],
        )


class TherapyProgramPaymentView(BaseCreateAPIView, ProgramPaymentViewMeta):
    serializer_class = ProgramPaymentHistorySerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]
    filter_kwargs = {"program_type": ProgramType.THERAPY, "therapy_program__isnull": False}

    def perform_create(self, serializer):
        serializer.save(program=self.get_program(), created_by=self.request.user)


class ProgramPaymentHistoryView(BaseListAPIView, ProgramPaymentViewMeta):
    serializer_class = ProgramPaymentHistorySerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def get_queryset(self):
        return ProgramPaymentHistory.objects.filter(
            program=self.get_program(),
        ).select_related("created_by").order_by("-created_at", "-pk")
