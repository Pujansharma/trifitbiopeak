from django.db.models import Prefetch

from accounts.utils.permissions import IsAdminUser, IsAssociateUser
from core.utils.exceptions import get_object_or_404
from core.utils.permissions import ReadOnly
from core.utils.views.main import (
    BaseGenericAPIView,
    BaseListCreateAPIView,
    BaseRetrieveUpdateAPIView,
)
from programs.services.consultation.serializers import ConsultationServiceSerializer
from programs.services.models import CenterServiceAssignment, Service
from programs.services.utils.constants import ServiceCategory


class ConsultationServiceViewMeta(BaseGenericAPIView):
    @classmethod
    def get_service_queryset(cls):
        return (
            Service.objects.filter(service_category=ServiceCategory.CONSULTATION)
            .select_related("created_by")
            .prefetch_related(
                Prefetch(
                    "center_assignments",
                    queryset=CenterServiceAssignment.objects.filter(
                        is_active=True,
                    ).select_related("center"),
                    to_attr="active_center_assignments",
                )
            )
        )

    def get_queryset(self):
        return self.get_service_queryset()

    def get_object(self):
        return get_object_or_404(
            self.get_service_queryset(),
            "Consultation service not found",
            pk=self.kwargs["pk"],
        )


class ConsultationServicesView(BaseListCreateAPIView, ConsultationServiceViewMeta):
    serializer_class = ConsultationServiceSerializer
    permission_classes = [IsAdminUser | (IsAssociateUser & ReadOnly)]

    def get_queryset(self):
        filter_kwargs = {}
        search_query = self.request.query_params.get("search", "").strip()
        active_query = self.request.query_params.get("active")
        if search_query:
            filter_kwargs["name__icontains"] = search_query
        if active_query in ["0", "1"]:
            filter_kwargs["is_active"] = active_query == "1"
        return self.get_service_queryset().filter(**filter_kwargs)

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ConsultationServiceDetailView(
    BaseRetrieveUpdateAPIView, ConsultationServiceViewMeta,
):
    serializer_class = ConsultationServiceSerializer
    permission_classes = [IsAdminUser | (IsAssociateUser & ReadOnly)]
