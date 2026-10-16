import arrow
from requests.exceptions import RequestException
from django.core.files.base import ContentFile
from django.utils import timezone

from core.utils.log import logger
from integrations.bugspeaks.tasks import process_bugspeaks_report_fetch
from integrations.bugspeaks.utils.helper import get_bugspeaks_record_payload
from integrations.bugspeaks.utils.sdk import (
    _get_bugspeaks_additional_file,
    _get_bugspeaks_file,
    get_bugspeaks_record,
)
from programs.composites.utils.db import (
    update_composite_program_document_counts,
    update_composite_program_results_count,
)
from programs.program_services.utils.db import (
    save_order_artifact,
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


def _fetch_bugspeaks_order_pdf(
    result_request: ResultRequest, api_key: str, identifier: str,
) -> str | None:
    try:
        pdf_file = _get_bugspeaks_file(api_key, identifier)
    except RequestException as exception:
        return f"pdf: {exception}"
    if pdf_file is None:
        return "BugSpeaks PDF report is not available."
    with pdf_file:
        content = pdf_file.getvalue()
    if not content:
        return "BugSpeaks PDF report was empty."
    save_order_artifact(
        result_request, ServiceDocumentType.BUGSPEAKS_REPORT, content, ".pdf",
        "application/pdf", ServiceDocumentCategory.REPORT,
    )
    return None


def _fetch_bugspeaks_order_additional_report(
    result_request: ResultRequest, api_key: str, identifier: str,
) -> str | None:
    try:
        additional_file = _get_bugspeaks_additional_file(api_key, identifier)
    except RequestException as exception:
        return f"additional report: {exception}"
    if additional_file is None:
        return "BugSpeaks additional report is not available."
    with additional_file:
        content = additional_file.getvalue()
    if not content:
        return "BugSpeaks additional report was empty."
    save_order_artifact(
        result_request, ServiceDocumentType.BUGSPEAKS_REPORT, content, ".xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ServiceDocumentCategory.RAW,
    )
    return None


def fetch_bugspeaks_order_reports(result_request: ResultRequest) -> tuple:
    api_key = (result_request.product.provider.api.data or {}).get("api_key")
    if not api_key:
        return None, "Report retrieval requires an api_key."
    identifier = result_request.data.get("bugspeaks_id")
    if not identifier:
        return None, "Report retrieval requires bugspeaks_id."
    record = None
    try:
        response, record_error = get_bugspeaks_record(api_key, identifier)
        record = get_bugspeaks_record_payload(response)
    except RequestException as exception:
        record_error = f"BugSpeaks report metadata: {exception}"
    if record:
        save_result_request_result(
            result_request, ServiceDocumentType.BUGSPEAKS_REPORT, defaults={"data": record},
        )
    if not record and not record_error:
        record_error = "BugSpeaks report metadata is not available."
    pdf_error = _fetch_bugspeaks_order_pdf(result_request, api_key, identifier)
    additional_error = _fetch_bugspeaks_order_additional_report(result_request, api_key, identifier)
    errors = list(filter(None, [record_error, pdf_error, additional_error]))
    has_output = ServiceDocument.objects.filter(
        result__result_request=result_request, result__document_type=ServiceDocumentType.BUGSPEAKS_REPORT,
        result__is_active=True, is_active=True,
    ).exists()
    result_request.status = ResultRequestStatus.COMPLETED
    if errors:
        result_request.status = ResultRequestStatus.PARTIALLY_FETCHED if has_output else ResultRequestStatus.PENDING
        logger.warning(f"BugSpeaks order reports incomplete: request={result_request.pk} reason={'; '.join(errors)}")
    result_request.failure_detail = "; ".join(errors)
    return True, None


def handle_bugspeaks_report_fetch(result_request: ResultRequest, provider_api_data: dict) -> None:
    """Fetch and persist the files for a BugSpeaks result request.

    This function is the reference flow for provider-backed result fetch
    handlers. It validates the required provider and request data, delegates
    remote API access to the BugSpeaks integration, creates one fetched
    ``ServiceResult`` with its report and raw-data documents, refreshes all
    affected result and program counters, and marks the request as completed.

    Expected provider or request failures mark ``result_request`` as failed
    and return without creating result records. Unexpected integration,
    storage, or database exceptions propagate to the calling request thread.

    Args:
        result_request: Persisted request containing the program service,
            product, creator, and ``data["bugspeaks_id"]``.
        provider_api_data: Provider configuration containing ``api_key``.

    Returns:
        None.
    """
    api_key = provider_api_data.get('api_key', "")

    if not api_key:
        _message = "API key is missing in provider configuration"
        logger.error(_message)
        result_request.status = ResultRequestStatus.FAILED
        result_request.failure_detail = _message
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

    _data = result_request.data or {}

    bugspeaks_id = _data.get('bugspeaks_id', "")
    if not bugspeaks_id:
        _message = "Bugspeaks ID not provided"
        logger.error(_message)
        result_request.status = ResultRequestStatus.FAILED
        result_request.failure_detail = _message
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

    metadata, result_files, error = process_bugspeaks_report_fetch(api_key, bugspeaks_id)

    if error:
        logger.error(f"API Error: {error}")
        result_request.status = ResultRequestStatus.FAILED
        result_request.failure_detail = error
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

    if len(result_files) < 2:
        logger.warning("Files are missing, expected 2, received 1.")

    _pdf_report, _raw_file = result_files
    program_service = result_request.program_service
    program_identifier = program_service.program.pk

    service_result = save_result_request_result(
        result_request,
        ServiceDocumentType.BUGSPEAKS_REPORT,
        defaults={
            "sample_collection_date": metadata.get("sample_pickup_date"),
            "report_generation_date": metadata.get("project_completed_timestamp"),
            "data": {
                **metadata,
                "sample_pickup_date": (
                    str(metadata["sample_pickup_date"]) if metadata.get("sample_pickup_date") else None
                ),
                "project_completed_timestamp": (
                    str(metadata["project_completed_timestamp"]) if metadata.get("project_completed_timestamp") else None
                ),
            },
        },
    )

    documents = []

    if _pdf_report:
        file_name = (
            f"BugSpeaks_PDF_Report_{bugspeaks_id}_"
            f"{int(arrow.now().timestamp())}.pdf"
        )
        file_content = _pdf_report.getvalue()
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

    if _raw_file:
        file_name = (
            f"BugSpeaks_Additional_Report_{bugspeaks_id}_"
            f"{int(arrow.now().timestamp())}.xlsx"
        )
        file_content = _raw_file.getvalue()
        file = ContentFile(content=file_content, name=file_name)
        documents.append(
            ServiceDocument(
                result=service_result,
                file=file,
                filename=file_name,
                content_type=(
                    "application/vnd.openxmlformats-officedocument."
                    "spreadsheetml.sheet"
                ),
                file_hash=generate_file_hash(file_content),
                document_category=ServiceDocumentCategory.RAW,
            )
        )
    ServiceDocument.objects.bulk_create(documents)
    update_result_documents_count(service_result.pk)
    update_program_service_results_count(program_service.pk)
    update_program_service_document_counts(program_service.pk)
    update_composite_program_results_count(program_identifier)
    update_composite_program_document_counts(program_identifier)

    result_request.status = ResultRequestStatus.COMPLETED
    result_request.completed_at = timezone.localtime()
    result_request.save(
        update_fields=["status", "completed_at", "updated_at"]
    )
    return None
