from functools import partial
from uuid import UUID

from django.core.files.base import ContentFile
from django.core.files.storage import Storage
from django.db import transaction
from django.db.models import Count, OuterRef, Subquery, Value
from django.db.models.functions import Coalesce

from programs.program_services.utils.helper import generate_file_hash
from programs.composites.utils.db import (
    update_composite_program_document_counts,
    update_composite_program_results_count,
)
from programs.models import ProgramService
from programs.services.models import ResultRequest, ServiceDocument, ServiceResult
from programs.services.utils.constants import (
    ResultRequestStatus,
    ResultType,
    ServiceDocumentCategory,
)


def save_order_artifact(
    result_request: ResultRequest, document_type: str, content: bytes, extension: str,
    content_type: str, category: str, defaults: dict | None = None,
) -> ServiceDocument:
    result = save_result_request_result(result_request, document_type, defaults=defaults)
    file_hash = generate_file_hash(content)
    document = get_or_create_order_document(result, result_request, file_hash, content, extension, content_type, category)
    update_result_documents_count(result.pk)
    return document


def get_or_create_order_document(
    result: ServiceResult, result_request: ResultRequest, file_hash: str,
    content: bytes, extension: str, content_type: str, category: str,
) -> ServiceDocument:
    document = ServiceDocument.objects.filter(
        result=result, file_hash=file_hash, document_category=category,
    ).first()
    filename = f"{result_request.pk}_{file_hash[:12]}{extension}"
    if not document:
        return ServiceDocument.objects.create(
            result=result, file=ContentFile(content, name=filename), filename=filename,
            content_type=content_type, file_hash=file_hash, document_category=category,
        )
    document.filename = filename
    document.content_type = content_type
    document.save(update_fields=["filename", "content_type", "updated_at"])
    return document


def save_result_request_result(
    result_request: ResultRequest,
    document_type: str,
    defaults: dict | None = None,
) -> ServiceResult:

    service_result, _ = ServiceResult.objects.update_or_create(
        result_request=result_request,
        document_type=document_type,
        defaults={
            **(defaults or {}),
            "program_service": result_request.program_service,
            "product": result_request.product,
            "provider_name": result_request.product.provider.name,
            "product_name": result_request.product.name,
            "result_mode": result_request.request_type,
            "created_by": result_request.created_by,
        },
    )
    return service_result


def update_result_documents_count(result_id: UUID):
    documents_count_subquery = (
        ServiceDocument.objects.filter(
            result=OuterRef("pk"),
        )
        .values("result")
        .annotate(count=Count("pk"))
        .values("count")
    )
    ServiceResult.objects.filter(pk=result_id).update(
        documents_count=Coalesce(
            Subquery(documents_count_subquery),
            Value(0),
        )
    )


def _get_program_service_result_requests_count_subquery(
    excluded_statuses=None,
):
    result_requests = ResultRequest.objects.filter(
        program_service=OuterRef("pk"),
    )
    if excluded_statuses:
        result_requests = result_requests.exclude(status__in=excluded_statuses)
    return (
        result_requests.values("program_service")
        .annotate(count=Count("pk"))
        .values("count")
    )


def _get_program_service_results_count_subquery(result_mode=None):
    filter_arguments = {
        "program_service": OuterRef("pk"),
    }
    if result_mode:
        filter_arguments["result_mode"] = result_mode
    return (
        ServiceResult.objects.filter(**filter_arguments)
        .values("program_service")
        .annotate(count=Count("pk"))
        .values("count")
    )


def update_program_service_results_count(
    program_service_identifier: UUID,
):
    results_count_subquery = _get_program_service_results_count_subquery()
    ProgramService.objects.filter(pk=program_service_identifier).update(
        results_count=Coalesce(
            Subquery(results_count_subquery),
            Value(0),
        )
    )


def _get_program_service_documents_count_subquery(
    document_category=None,
    result_mode=None,
):
    filter_arguments = {
        "result__program_service": OuterRef("pk"),
    }
    if document_category:
        filter_arguments["document_category"] = document_category
    if result_mode:
        filter_arguments["result__result_mode"] = result_mode
    return (
        ServiceDocument.objects.filter(**filter_arguments)
        .values("result__program_service")
        .annotate(count=Count("pk"))
        .values("count")
    )


def update_program_service_document_counts(
    program_service_identifier: UUID,
):
    documents_count_subquery = _get_program_service_documents_count_subquery()
    reports_count_subquery = _get_program_service_documents_count_subquery(
        ServiceDocumentCategory.REPORT
    )
    raw_data_count_subquery = _get_program_service_documents_count_subquery(
        ServiceDocumentCategory.RAW
    )
    ProgramService.objects.filter(pk=program_service_identifier).update(
        documents_count=Coalesce(
            Subquery(documents_count_subquery),
            Value(0),
        ),
        reports_count=Coalesce(
            Subquery(reports_count_subquery),
            Value(0),
        ),
        raw_data_count=Coalesce(
            Subquery(raw_data_count_subquery),
            Value(0),
        ),
    )


def _get_program_service_fetch_count_update_values():
    fetch_count_subquery = _get_program_service_result_requests_count_subquery()
    fetch_results_count_subquery = _get_program_service_results_count_subquery(
        ResultType.FETCH
    )
    fetch_documents_count_subquery = (
        _get_program_service_documents_count_subquery(
            result_mode=ResultType.FETCH,
        )
    )
    fetch_pending_count_subquery = (
        _get_program_service_result_requests_count_subquery(
            excluded_statuses=[
                ResultRequestStatus.COMPLETED,
                ResultRequestStatus.FAILED,
                ResultRequestStatus.CANCELLED,
            ]
        )
    )
    return {
        "fetch_count": Coalesce(Subquery(fetch_count_subquery), Value(0)),
        "fetch_results_count": Coalesce(
            Subquery(fetch_results_count_subquery),
            Value(0),
        ),
        "fetch_documents_count": Coalesce(
            Subquery(fetch_documents_count_subquery),
            Value(0),
        ),
        "fetch_pending_count": Coalesce(
            Subquery(fetch_pending_count_subquery),
            Value(0),
        ),
    }


def update_program_service_fetch_counts(
    program_service_identifier: UUID,
):
    ProgramService.objects.filter(pk=program_service_identifier).update(
        **_get_program_service_fetch_count_update_values()
    )


def update_all_result_documents_count():
    documents_count_subquery = (
        ServiceDocument.objects.filter(
            result=OuterRef("pk"),
        )
        .values("result")
        .annotate(count=Count("pk"))
        .values("count")
    )
    return ServiceResult.objects.update(
        documents_count=Coalesce(
            Subquery(documents_count_subquery),
            Value(0),
        )
    )


def update_all_program_service_results_count():
    results_count_subquery = _get_program_service_results_count_subquery()
    return ProgramService.objects.update(
        results_count=Coalesce(
            Subquery(results_count_subquery),
            Value(0),
        )
    )


def update_all_program_service_document_counts():
    documents_count_subquery = _get_program_service_documents_count_subquery()
    reports_count_subquery = _get_program_service_documents_count_subquery(
        ServiceDocumentCategory.REPORT
    )
    raw_data_count_subquery = _get_program_service_documents_count_subquery(
        ServiceDocumentCategory.RAW
    )
    return ProgramService.objects.update(
        documents_count=Coalesce(
            Subquery(documents_count_subquery),
            Value(0),
        ),
        reports_count=Coalesce(
            Subquery(reports_count_subquery),
            Value(0),
        ),
        raw_data_count=Coalesce(
            Subquery(raw_data_count_subquery),
            Value(0),
        ),
    )


def update_all_program_service_fetch_counts():
    return ProgramService.objects.update(
        **_get_program_service_fetch_count_update_values()
    )


def _delete_stored_file(storage: Storage, file_name: str):
    storage.delete(file_name)


def delete_service_document(service_document: ServiceDocument):
    result_identifier = service_document.result.pk
    program_service_identifier = service_document.result.program_service.pk
    program_identifier = service_document.result.program_service.program.pk
    file_storage = service_document.file.storage
    file_name = service_document.file.name

    with transaction.atomic():
        service_document.delete()
        update_result_documents_count(result_identifier)
        update_program_service_document_counts(program_service_identifier)
        update_program_service_fetch_counts(program_service_identifier)
        update_composite_program_document_counts(program_identifier)
        if file_name:
            transaction.on_commit(
                partial(_delete_stored_file, file_storage, file_name)
            )


def delete_service_result(service_result: ServiceResult):
    program_service_identifier = service_result.program_service.pk
    program_identifier = service_result.program_service.program.pk

    with transaction.atomic():
        document_files = [
            (service_document.file.storage, service_document.file.name)
            for service_document in ServiceDocument.objects.filter(
                result=service_result,
            ).only("file")
        ]
        service_result.delete()
        update_program_service_results_count(program_service_identifier)
        update_program_service_document_counts(program_service_identifier)
        update_program_service_fetch_counts(program_service_identifier)
        update_composite_program_results_count(program_identifier)
        update_composite_program_document_counts(program_identifier)
        for file_storage, file_name in document_files:
            if file_name:
                transaction.on_commit(
                    partial(_delete_stored_file, file_storage, file_name)
                )
