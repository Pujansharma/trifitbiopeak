from django.db.models import Q

from accounts.utils.constants import UserType
from accounts.utils.db import get_user_account_type
from accounts.utils.permissions import BaseAssociateRBACPermission, IsAdminUser
from core.utils.exceptions import get_object_or_404
from core.utils.views.main import (
    BaseGenericAPIView,
    BaseListCreateAPIView,
    BaseRetrieveDestroyAPIView,
)
from programs.models import ConsultationDocument, ProgramService
from programs.consultation.serializers import (
    ConsultationDocumentFilterSerializer,
    ConsultationDocumentSerializer,
    validate_consultation_program_service,
)
from programs.consultation.utils.db import delete_consultation_document
from programs.services.utils.constants import ServiceCategory
from programs.utils.constants import ProgramType


class ConsultationAccessMixin:
    def get_consultation_service_scope(self):
        program_services = ProgramService.objects.filter(
            program__program_type=ProgramType.COMPOSITE,
            program__composite_program__isnull=False,
            service__service_category=ServiceCategory.CONSULTATION,
            consultation_service__isnull=False,
        )
        if get_user_account_type(self.request.user) == UserType.ASSOCIATE:
            program_services = program_services.filter(
                Q(program__center__pk=self.request.center_id)
                | Q(program__redeemable_centers__pk=self.request.center_id),
            )
        return program_services.distinct()

    def filter_consultation_queryset(self, queryset, serializer_class):
        filters = serializer_class(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return queryset.filter(**filters.validated_data)


class ConsultationProgramServiceViewMeta(ConsultationAccessMixin, BaseGenericAPIView):
    filter_kwargs = {}

    def get_consultation_program_service_queryset(self):
        return self.get_consultation_service_scope().filter(**self.filter_kwargs).select_related(
            "consultation_service", "program__composite_program",
        )

    def get_consultation_program_service(self):
        return get_object_or_404(
            self.get_consultation_program_service_queryset(),
            "Consultation program service not found.",
            pk=self.kwargs["pk"],
        )


class ConsultationDocumentViewMeta(ConsultationAccessMixin, BaseGenericAPIView):
    filter_kwargs = {}

    def get_consultation_document_queryset(self):
        return ConsultationDocument.objects.filter(
            consultation_program_service__program_service__in=self.get_consultation_service_scope(),
            **self.filter_kwargs,
        ).select_related(
            "consultation_program_service__program_service__program__composite_program",
            "created_by",
        )

    def get_queryset(self):
        return self.get_consultation_document_queryset()


class ConsultationProgramServiceDocumentsViewMeta(ConsultationProgramServiceViewMeta):
    def get_queryset(self):
        program_service = self.get_consultation_program_service()
        documents = ConsultationDocument.objects.filter(
            consultation_program_service=program_service.consultation_service,
        ).select_related("created_by")
        return self.filter_consultation_queryset(documents, ConsultationDocumentFilterSerializer)


class ConsultationProgramServiceDocumentsView(
    BaseListCreateAPIView, ConsultationProgramServiceDocumentsViewMeta,
):
    serializer_class = ConsultationDocumentSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def perform_create(self, serializer):
        serializer.save(
            program_service=self.get_consultation_program_service(),
            created_by=self.request.user,
        )


class ConsultationDocumentDetailView(BaseRetrieveDestroyAPIView, ConsultationDocumentViewMeta):
    serializer_class = ConsultationDocumentSerializer
    permission_classes = [IsAdminUser | BaseAssociateRBACPermission]

    def perform_destroy(self, instance: ConsultationDocument):
        validate_consultation_program_service(instance.consultation_program_service.program_service)
        delete_consultation_document(instance)
