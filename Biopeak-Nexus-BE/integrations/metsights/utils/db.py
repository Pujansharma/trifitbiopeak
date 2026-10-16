"""Queries, pandas collection and persistence for the MetSights callers."""

from pathlib import Path
from typing import BinaryIO

import pandas as pd
from requests.exceptions import RequestException
from django.core.files import File
from django.db.models import F, FilteredRelation, Q

from accounts.customers.models import CustomerProfile
from core.utils.exceptions import ServiceUnavailable
from integrations.metsights.utils.profiles import get_or_create_metsights_profile
from integrations.metsights.models import MetsightsProfile
from programs.composites.utils.db import (
    update_composite_program_results_count, update_composite_program_document_counts,
)
from programs.models import Program
from programs.program_services.utils.db import (
    save_result_request_result,
    update_result_documents_count, update_program_service_results_count,
    update_program_service_document_counts, update_program_service_fetch_counts,
)
from programs.program_services.utils.helper import generate_file_hash
from programs.services.models import ResultRequest, ServiceDocument, ServiceResult
from programs.services.utils.constants import (
    ServiceDocumentCategory, ServiceDocumentType,
)


def set_request_status(result_request: ResultRequest, status: str, detail: str = "") -> None:
    result_request.status = status
    result_request.failure_detail = detail


def collect_program_documents(program: Program):
    """Return one flat table containing source metadata and its document rows."""
    columns = [
        "service_result_id", "document_type", "data", "sample_collection_date",
        "report_generation_date", "created_at", "document_id", "file", "filename",
        "content_type", "file_hash", "document_category",
    ]
    rows = ServiceResult.objects.filter(
        program_service__program=program, program_service__is_active=True, is_active=True,
    ).exclude(document_type=ServiceDocumentType.METSIGHTS_PP).annotate(
        active_documents=FilteredRelation("documents", condition=Q(documents__is_active=True)),
        service_result_id=F("pk"), document_id=F("active_documents__pk"),
        file=F("active_documents__file"), filename=F("active_documents__filename"),
        content_type=F("active_documents__content_type"), file_hash=F("active_documents__file_hash"),
        document_category=F("active_documents__document_category"),
    ).values(*columns)
    return pd.DataFrame(list(rows), columns=columns, dtype=object)


def get_metsights_result(result_request: ResultRequest):
    return ServiceResult.objects.filter(
        result_request=result_request, document_type=ServiceDocumentType.METSIGHTS_PP,
    ).first()


def get_or_create_metsights_result(result_request: ResultRequest) -> ServiceResult:
    record_id = (result_request.data or {}).get("record_id")
    result = save_result_request_result(result_request, ServiceDocumentType.METSIGHTS_PP)
    data = {
        "report_data": None,
        "analysis_data": None,
        "trends_data": None,
        "files_data": {},
        **(result.data or {}),
        "metsights_record_id": record_id,
    }
    if result.data != data:
        result.data = data
        result.save(update_fields=["data", "updated_at"])
    return result


def save_report_data(
        result_request: ResultRequest, key: str, payload: object, replace_existing: bool,
) -> ServiceResult:
    result = get_or_create_metsights_result(result_request)
    data = result.data or {}
    if data.get(key) is None or replace_existing:
        result.data = {**data, key: payload}
        result.save(update_fields=["data", "updated_at"])
    return result


def save_report_file_data(
        result_request: ResultRequest, remote_file_id: str, payload: object, replace_existing: bool,
) -> ServiceResult:
    result = get_or_create_metsights_result(result_request)
    data = result.data or {}
    files_data = data.get("files_data") or {}
    if files_data.get(remote_file_id) is None or replace_existing:
        result.data = {
            **data,
            "files_data": {**files_data, remote_file_id: payload},
        }
        result.save(update_fields=["data", "updated_at"])
    return result


def get_existing_report_document(result_request: ResultRequest, document_identifier: str):
    return ServiceDocument.objects.filter(
        pk=document_identifier, result__result_request=result_request, is_active=True,
    ).first()


def save_report_document(
        result_request: ResultRequest, artifact: dict, downloaded_file: BinaryIO, content_type: str,
) -> ServiceDocument | None:
    result = get_or_create_metsights_result(result_request)
    filename = Path(artifact["filename"]).name[:255]
    document = ServiceDocument(
        result=result,
        filename=filename,
        content_type=content_type[:127],
        document_category=artifact.get("category", ServiceDocumentCategory.REPORT),
        report_component=artifact.get("report_component"),
    )
    document.file.save(filename, File(downloaded_file, name=filename), save=False)
    if not document.file.size:
        return None
    with document.file.open("rb") as saved_file:
        document.file_hash = generate_file_hash(saved_file)
    existing_document = ServiceDocument.objects.filter(
        result=result,
        report_component=document.report_component,
        file_hash=document.file_hash,
    ).first()
    if existing_document:
        return existing_document
    document.save()
    return document


def refresh_metsights_counts(result_request: ResultRequest):
    result = get_metsights_result(result_request)
    service = result_request.program_service
    if result:
        update_result_documents_count(result.pk)
    update_program_service_results_count(service.pk)
    update_program_service_document_counts(service.pk)
    update_program_service_fetch_counts(service.pk)
    update_composite_program_results_count(service.program.pk)
    update_composite_program_document_counts(service.program.pk)


def create_metsights_profile_for_customer_profile(customer_profile: CustomerProfile) -> MetsightsProfile | None:
    """Obtain and persist a missing or empty MetSights profile mapping."""
    mapping = MetsightsProfile.objects.filter(customer_profile=customer_profile).first()
    if mapping and mapping.profile_id:
        return mapping
    try:
        profile_identifier = get_or_create_metsights_profile(
            phone=customer_profile.customer.user.phone,
            email=customer_profile.customer.contact_email,
            first_name=customer_profile.first_name, last_name=customer_profile.last_name,
            gender=customer_profile.gender, date_of_birth=customer_profile.date_of_birth,
        )
    except RequestException as error:
        raise ServiceUnavailable("MetSights profile mapping is unavailable.") from error
    if not profile_identifier:
        return None
    mapping, _ = MetsightsProfile.objects.update_or_create(
        customer_profile=customer_profile, defaults={"profile_id": profile_identifier},
    )
    return mapping
