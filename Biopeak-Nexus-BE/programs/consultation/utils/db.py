from functools import partial

from django.db import transaction
from django.db.models import Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from core.utils.log import logger
from programs.models import (
    CompositeProgram,
    ConsultationDocument,
    ConsultationProgramService,
    ProgramService,
)
from programs.program_services.utils.db import _delete_stored_file


def update_consultation_counts(
    consultation_service: ConsultationProgramService | None = None,
) -> tuple[int, int]:
    """Recompute consultation totals for one service or all retained records."""
    service_documents = (
        ConsultationDocument.objects.filter(consultation_program_service=OuterRef("pk"))
        .order_by().values("consultation_program_service")
        .annotate(count=Count("pk")).values("count")
    )
    composite_documents = (
        ConsultationDocument.objects.filter(
            consultation_program_service__program_service__program=OuterRef("program"),
        ).order_by().values("consultation_program_service__program_service__program")
        .annotate(count=Count("pk")).values("count")
    )
    consultation_services = ConsultationProgramService.objects.all()
    program_services = ProgramService.objects.filter(consultation_service__isnull=False)
    composite_programs = CompositeProgram.objects.all()
    if consultation_service is not None:
        consultation_services = consultation_services.filter(pk=consultation_service.pk)
        program_services = program_services.filter(consultation_service=consultation_service)
        composite_programs = composite_programs.filter(
            program=consultation_service.program_service.program,
        )

    service_documents_count = Coalesce(Subquery(service_documents), Value(0))
    composite_documents_count = Coalesce(Subquery(composite_documents), Value(0))
    updated_services = consultation_services.update(
        documents_count=service_documents_count,
    )
    program_services.update(
        documents_count=service_documents_count,
    )
    updated_composites = composite_programs.update(
        consultation_documents_count=composite_documents_count,
        consultation_files_count=composite_documents_count,
    )
    return updated_services, updated_composites


def recompute_all_consultation_counts() -> tuple[int, int, int]:
    documents = ConsultationDocument.objects.update(files_count=1)
    services, composites = update_consultation_counts()
    logger.info(
        f"recompute_all_consultation_counts: updated documents={documents}, "
        f"consultation_services={services}, composite_programs={composites}."
    )
    return documents, services, composites


@transaction.atomic
def delete_consultation_document(document: ConsultationDocument) -> None:
    consultation_service = document.consultation_program_service
    document_identifier = document.pk
    storage = document.file.storage
    filename = document.file.name
    document.delete()
    update_consultation_counts(consultation_service)
    if filename:
        transaction.on_commit(partial(_delete_stored_file, storage, filename))
    logger.info(
        f"delete_consultation_document: deleted document={document_identifier}, "
        f"consultation_service={consultation_service.pk}."
    )
