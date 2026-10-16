import arrow
from requests.exceptions import RequestException
from django.core.files.base import ContentFile
from django.utils import timezone

from core.utils.log import logger
from integrations.strand_genomics.utils.helper import process_strand_genomics_report_fetch
from integrations.strand_genomics.utils.sdk import get_order_status, get_pdf_report, get_vcf_file, get_report_data
from programs.composites.utils.db import (
    update_composite_program_results_count,
    update_composite_program_document_counts
)
from programs.program_services.utils.db import (
    save_order_artifact,
    save_result_request_result,
    update_result_documents_count, update_program_service_results_count,
    update_program_service_document_counts
)
from programs.program_services.utils.helper import generate_file_hash
from programs.services.models import ResultRequest, ServiceDocument
from programs.services.utils.constants import (
    ResultRequestStatus, ServiceDocumentType,
    ServiceDocumentCategory
)


def _fetch_strand_order_pdf(
    result_request: ResultRequest, identifier: str, api_key: str, document_type: str,
    sample_collection_date: str | None,
) -> str | None:
    if ServiceDocument.objects.filter(
        result__result_request=result_request, document_category=ServiceDocumentCategory.REPORT, is_active=True,
    ).exists():
        return None
    try:
        pdf_file, error = get_pdf_report(identifier, api_key)
    except RequestException as exception:
        return f"pdf: {exception}"
    if pdf_file is None:
        return error or "Strand PDF report is not available."
    with pdf_file:
        content = pdf_file.getvalue()
    if not content:
        return "Strand PDF report was empty."
    save_order_artifact(
        result_request, document_type, content, ".pdf", "application/pdf", ServiceDocumentCategory.REPORT,
        defaults={"sample_collection_date": sample_collection_date},
    )
    return None


def _fetch_strand_order_vcf(
    result_request: ResultRequest, identifier: str, api_key: str, document_type: str,
    sample_collection_date: str | None,
) -> str | None:
    if ServiceDocument.objects.filter(
        result__result_request=result_request, document_category=ServiceDocumentCategory.RAW, is_active=True,
    ).exists():
        return None
    try:
        vcf_file, error = get_vcf_file(identifier, api_key)
    except RequestException as exception:
        return f"vcf: {exception}"
    if vcf_file is None:
        return error or "Strand VCF file is not available."
    with vcf_file:
        content = vcf_file.getvalue()
    if not content:
        return "Strand VCF file was empty."
    save_order_artifact(
        result_request, document_type, content, ".vcf", "text/plain", ServiceDocumentCategory.RAW,
        defaults={"sample_collection_date": sample_collection_date},
    )
    return None


def _fetch_strand_order_json(
    result_request: ResultRequest, identifier: str, api_key: str, document_type: str,
    sample_collection_date: str | None,
) -> str | None:
    try:
        report_data, error = get_report_data(identifier, api_key)
    except RequestException as exception:
        return f"json: {exception}"
    if not report_data:
        return error or "Strand JSON report is not available."
    save_result_request_result(
        result_request, document_type,
        defaults={"data": report_data, "sample_collection_date": sample_collection_date},
    )
    return None


def _fetch_strand_order_reports(
    result_request: ResultRequest, document_type: str, expected_test_names: tuple[str, ...],
) -> tuple[bool | None, str | None]:
    api_key = (result_request.product.provider.api.data or {}).get("api_key")
    if not api_key:
        return None, "Report retrieval requires an api_key."
    identifier = result_request.data.get("request_id")
    if not identifier:
        return None, "Report retrieval requires request_id."
    try:
        status_data, error = get_order_status(identifier, api_key)
    except RequestException as exception:
        return None, f"Strand order status: {exception}"
    if error:
        return None, error
    if not isinstance(status_data, list) or not status_data or not isinstance(status_data[0], dict):
        return None, "Strand order status did not contain a report record."
    test_name = (status_data[0].get("Name_of_the_Test") or "").strip().lower()
    if test_name not in expected_test_names:
        return None, f"Unexpected Strand test name: {test_name}."
    sample_collection_date = result_request.data.get("sample_collection_date")
    pdf_error = _fetch_strand_order_pdf(
        result_request, identifier, api_key, document_type, sample_collection_date,
    )
    vcf_error = _fetch_strand_order_vcf(
        result_request, identifier, api_key, document_type, sample_collection_date,
    )
    json_error = _fetch_strand_order_json(
        result_request, identifier, api_key, document_type, sample_collection_date,
    )
    errors = list(filter(None, [pdf_error, vcf_error, json_error]))
    has_output = json_error is None or ServiceDocument.objects.filter(
        result__result_request=result_request, result__document_type=document_type,
        result__is_active=True, is_active=True,
    ).exists()
    result_request.status = ResultRequestStatus.COMPLETED
    if errors:
        result_request.status = ResultRequestStatus.PARTIALLY_FETCHED if has_output else ResultRequestStatus.PENDING
        logger.warning(f"Strand order reports incomplete: request={result_request.pk} reason={'; '.join(errors)}")
    result_request.failure_detail = "; ".join(errors)
    return True, None


def fetch_strand_nutri_dna_order_reports(result_request: ResultRequest) -> tuple[bool | None, str | None]:
    return _fetch_strand_order_reports(
        result_request, ServiceDocumentType.GENETICS_NUTRI_DNA, ("nutridna",),
    )


def fetch_strand_ghi_order_reports(result_request: ResultRequest) -> tuple[bool | None, str | None]:
    return _fetch_strand_order_reports(
        result_request, ServiceDocumentType.GENETICS_HEALTH_INSIGHTS,
        ("genomic health insights", "genomic health insights - wes"),
    )


def _process_result_data(
        request_id,
        result_files,
        result_request,
        service_document_type,
        file_name_prefix,
):
    _pdf_report, _vcf_file, _json_data = result_files

    program_service = result_request.program_service
    program_identifier = program_service.program.pk
    logger.info(
        f"STRAND_001 Strand Genomics Result Fetch persistence started: "
        f"result_request_id={result_request.pk} request_id={request_id}"
    )

    service_result = save_result_request_result(result_request, service_document_type)

    documents = []

    if _pdf_report:
        file_name = (
            f"{file_name_prefix}_Report_{request_id}_"
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
    if _vcf_file:
        file_name = (
            f"{file_name_prefix}_VCF_{request_id}_"
            f"{int(arrow.now().timestamp())}.vcf"
        )
        file_content = _vcf_file.getvalue()
        file = ContentFile(content=file_content, name=file_name)
        documents.append(
            ServiceDocument(
                result=service_result,
                file=file,
                filename=file_name,
                content_type="text/plain; charset=utf-8",
                file_hash=generate_file_hash(file_content),
                document_category=ServiceDocumentCategory.RAW,
            )
        )

    if _json_data:
        service_result.data = _json_data
        service_result.save(update_fields=['data', 'updated_at'])

    ServiceDocument.objects.bulk_create(documents)
    update_result_documents_count(service_result.pk)
    update_program_service_results_count(program_service.pk)
    update_program_service_document_counts(program_service.pk)
    update_composite_program_results_count(program_identifier)
    update_composite_program_document_counts(program_identifier)

    logger.info(
        f"STRAND_001 Strand Genomics Result Fetch persistence completed: "
        f"result_request_id={result_request.pk} request_id={request_id} "
        f"service_result_id={service_result.pk} "
        f"documents_count={len(documents)} json_available={bool(_json_data)}"
    )
    return service_result


def _handle_strand_report_fetch(
        result_request,
        provider_api_data,
        expected_report_type,
        service_document_type,
        file_name_prefix,
):
    logger.info(
        f"STRAND_001 Strand Genomics Result Fetch started: "
        f"result_request_id={result_request.pk} "
        f"report_type={expected_report_type}"
    )
    api_key = provider_api_data.get('api_key', "")

    if not api_key:
        _message = "API key is missing in provider configuration"
        logger.error(
            f"STRAND_001 Strand Genomics Result Fetch failed: "
            f"result_request_id={result_request.pk} error={_message}"
        )
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

    request_id = _data.get('request_id', "")
    if not request_id:
        _message = "Request ID not provided"
        logger.error(
            f"STRAND_001 Strand Genomics Result Fetch failed: "
            f"result_request_id={result_request.pk} error={_message}"
        )
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

    metadata, result_files, error = process_strand_genomics_report_fetch(
        api_key,
        request_id,
    )

    if not metadata:
        _message = error or "Strand Genomics report metadata was not available"
        logger.error(
            f"STRAND_001 Strand Genomics Result Fetch failed: "
            f"result_request_id={result_request.pk} request_id={request_id} "
            f"error={_message}"
        )
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

    test_name = metadata.get('test_name')
    if (
            not test_name
            or str(test_name).strip().lower() != expected_report_type.lower()
    ):
        _message = (
            f"Invalid Test name provided, expected {expected_report_type} "
            f"received: {test_name}"
        )
        logger.error(
            f"STRAND_001 Strand Genomics Result Fetch failed: "
            f"result_request_id={result_request.pk} request_id={request_id} "
            f"error={_message}"
        )
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

    logger.info(
        f"STRAND_001 Strand Genomics Result Fetch metadata validated: "
        f"result_request_id={result_request.pk} request_id={request_id} "
        f"test_name={test_name}"
    )
    _pdf_report, _vcf_file, _json_data = result_files
    available_artifacts_count = sum(
        [
            _pdf_report is not None,
            _vcf_file is not None,
            bool(_json_data),
        ]
    )
    logger.info(
        f"STRAND_001 Strand Genomics Result Fetch artifact summary: "
        f"result_request_id={result_request.pk} request_id={request_id} "
        f"pdf_available={_pdf_report is not None} "
        f"vcf_available={_vcf_file is not None} "
        f"json_available={bool(_json_data)}"
    )
    if not available_artifacts_count:
        _message = error or "No Strand Genomics report artifacts were available"
        logger.error(
            f"STRAND_001 Strand Genomics Result Fetch failed: "
            f"result_request_id={result_request.pk} request_id={request_id} "
            f"error={_message}"
        )
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

    service_result = _process_result_data(
        request_id,
        result_files,
        result_request,
        service_document_type,
        file_name_prefix,
    )
    if available_artifacts_count == 3:
        result_request.status = ResultRequestStatus.COMPLETED
        result_request.failure_detail = ""
        logger.info(
            f"STRAND_001 Strand Genomics Result Fetch completed: "
            f"result_request_id={result_request.pk} request_id={request_id} "
            f"service_result_id={service_result.pk}"
        )
    else:
        result_request.status = ResultRequestStatus.PARTIALLY_FETCHED
        result_request.failure_detail = (
                error or "Strand Genomics report artifacts were partially fetched"
        )
        logger.warning(
            f"STRAND_001 Strand Genomics Result Fetch partially fetched: "
            f"result_request_id={result_request.pk} request_id={request_id} "
            f"service_result_id={service_result.pk} "
            f"error={result_request.failure_detail}"
        )
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


def handle_strand_nutri_dna_report_fetch(
        result_request: ResultRequest, provider_api_data: dict
):
    _handle_strand_report_fetch(
        result_request=result_request,
        provider_api_data=provider_api_data,
        expected_report_type="NutriDNA",
        service_document_type=ServiceDocumentType.GENETICS_NUTRI_DNA,
        file_name_prefix="GenomicsNutriDNA",
    )


def handle_strand_ghi_report_fetch(
        result_request: ResultRequest, provider_api_data: dict
):
    _handle_strand_report_fetch(
        result_request=result_request,
        provider_api_data=provider_api_data,
        expected_report_type="Genomic Health Insights",
        service_document_type=ServiceDocumentType.GENETICS_HEALTH_INSIGHTS,
        file_name_prefix="GenomicsHealthInsights",
    )
