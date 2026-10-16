from io import BytesIO

from django.core.files.base import ContentFile
from django.utils import timezone

from core.utils.log import logger
from integrations.orange_labs.utils.helper import get_orange_result_dates
from programs.composites.utils.db import (
    update_composite_program_document_counts,
    update_composite_program_results_count,
)
from programs.program_services.utils.db import (
    save_result_request_result,
    update_program_service_document_counts,
    update_program_service_results_count,
    update_result_documents_count,
)
from programs.program_services.utils.helper import generate_file_hash
from programs.services.models import ResultRequest, ServiceDocument
from programs.services.utils.constants import (
    ResultRequestStatus,
    ServiceDocumentCategory,
    ServiceDocumentType,
)


def mark_orange_result_request_failed(
        result_request: ResultRequest,
        error_message: str,
):
    logger.error(
        f"OrangeHealth result fetch failed: "
        f"result_request_id={result_request.pk} error={error_message}"
    )
    result_request.status = ResultRequestStatus.FAILED
    result_request.failure_detail = error_message
    result_request.completed_at = timezone.localtime()
    result_request.save(
        update_fields=[
            "status",
            "failure_detail",
            "completed_at",
            "updated_at",
        ]
    )
    return None


def mark_orange_result_request_completed(result_request: ResultRequest):
    result_request.status = ResultRequestStatus.COMPLETED
    result_request.failure_detail = ""
    result_request.completed_at = timezone.localtime()
    result_request.save(
        update_fields=[
            "status",
            "failure_detail",
            "completed_at",
            "updated_at",
        ]
    )
    return None


def save_orange_result_data(
        metadata: dict,
        result_files: tuple[BytesIO, ...],
        result_request: ResultRequest,
):
    """Persist one Blood result and the already downloaded order reports."""
    program_service = result_request.program_service
    program_identifier = program_service.program.pk
    logger.info(
        f"OrangeHealth result persistence started: "
        f"result_request_id={result_request.pk}"
    )

    service_result = save_result_request_result(
        result_request,
        ServiceDocumentType.BLOOD,
        defaults={
            "data": metadata,
            **get_orange_result_dates(metadata["orders"]),
        },
    )

    documents = []
    for order, pdf_report in zip(metadata["orders"], result_files, strict=True):
        file_name = order["report_file_name"]
        with pdf_report:
            file_content = pdf_report.getvalue()
        file = ContentFile(content=file_content, name=file_name)
        documents.append(
            ServiceDocument(
                result=service_result,
                file=file,
                filename=file_name,
                content_type="application/pdf",
                file_hash=generate_file_hash(file_content),
                document_category=ServiceDocumentCategory.REPORT,
            )
        )

    ServiceDocument.objects.bulk_create(documents)
    update_result_documents_count(service_result.pk)
    update_program_service_results_count(program_service.pk)
    update_program_service_document_counts(program_service.pk)
    update_composite_program_results_count(program_identifier)
    update_composite_program_document_counts(program_identifier)

    logger.info(
        f"OrangeHealth result persistence completed: "
        f"result_request_id={result_request.pk} "
        f"service_result_id={service_result.pk}"
    )
    return service_result
