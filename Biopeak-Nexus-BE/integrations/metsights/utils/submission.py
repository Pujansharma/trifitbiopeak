"""Submit MetSights inputs and collect submission state in memory."""

from django.core.files.storage import default_storage
from django.utils import timezone

from integrations.metsights.models import MetsightsProfile
from integrations.metsights.utils.sdk import GENDER_MAPPING
from integrations.metsights.utils.db import collect_program_documents, set_request_status
from integrations.metsights.utils.documents import get_source_module, get_source_file_type
from integrations.metsights.utils.helper import create_attachment, create_profile, create_record, upload_document
from integrations.metsights.utils.results import handle_metsights_report_fetch
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus


def submit_metsights_request(
        result_request: ResultRequest,
        provider_api_data: dict
) -> str | None:
    api_key: str = provider_api_data.get("api_key") or ""
    subscription_id: str = provider_api_data.get("subscription_id") or ""
    if not api_key or not subscription_id:
        set_request_status(
            result_request,
            ResultRequestStatus.FAILED,
            "Provider API requires api_key and subscription_id."
        )
        return None

    service = result_request.program_service
    profile = service.program.customer_profile
    progress = result_request.data.setdefault("submission", {"sessions": {}})
    sessions = progress.setdefault("sessions", {})
    record_id: str = (service.data or {}).get("record_id") or ""
    if not record_id:
        mapping = MetsightsProfile.objects.filter(
            customer_profile=profile
        ).first()
        if mapping and not mapping.profile_id:
            set_request_status(
                result_request,
                ResultRequestStatus.FAILED,
                "The saved MetSights profile has no provider ID."
            )
            return None
        if not mapping:
            if not profile.date_of_birth or profile.gender not in GENDER_MAPPING:
                set_request_status(
                    result_request,
                    ResultRequestStatus.FAILED,
                    "MetSights requires a birth date and a supported gender."
                )
                return None
            response, error = create_profile(
                api_key=api_key, gender=profile.gender, date_of_birth=profile.date_of_birth,
            )
            if error:
                return error
            mapping = MetsightsProfile.objects.create(
                customer_profile=profile, profile_id=response["id"],
            )

        response, error = create_record(api_key, mapping.profile_id, subscription_id)
        if error:
            return error
        record_id = response["id"]
        service.data = {**(service.data or {}), "record_id": record_id}
        service.save(update_fields=["data", "updated_at"])
    result_request.data["record_id"] = record_id

    errors = []
    documents_frame = collect_program_documents(service.program)
    for service_result_id, group in documents_frame.groupby("service_result_id", sort=False):
        source = group.iloc[0].to_dict()
        documents = group.loc[group["document_id"].notna()].to_dict("records")
        if not documents and source["data"] is None:
            continue
        module_type = get_source_module(source["document_type"])
        if not module_type:
            errors.append(f"Result {service_result_id}: unsupported type {source['document_type']}.")
            continue
        routed_documents = []
        for document in documents:
            file_type, error = get_source_file_type(source["document_type"], document)
            if error:
                errors.append(error)
                continue
            document["file_type"] = file_type
            routed_documents.append(document)
        if not routed_documents and source["data"] is None:
            continue
        session_key = str(service_result_id)
        session = sessions.get(session_key)
        if not session:
            assessment_date = source["sample_collection_date"] or source["report_generation_date"]
            if not assessment_date:
                assessment_date = timezone.localtime(source["created_at"]).date()
            response, error = create_attachment(
                api_key=api_key,
                record_id=record_id,
                module_type=module_type,
                assessment_date=assessment_date,
                data=source["data"],
            )
            if error:
                return error
            session = {"attachment_id": response["id"], "documents": {}}
            sessions[session_key] = session
        for document in routed_documents:
            document_key = str(document["document_id"])
            if document_key in session["documents"]:
                continue
            with default_storage.open(document["file"], "rb") as uploaded_file:
                response, error = upload_document(
                    api_key=api_key, attachment_id=session["attachment_id"],
                    uploaded_file=uploaded_file, filename=document["filename"],
                    content_type=document["content_type"], file_type=document["file_type"],
                    attachment_date=source["report_generation_date"],
                )
            if error:
                return error
            session["documents"][document_key] = {
                "document_id": response["id"], "file_hash": document["file_hash"],
            }
    progress["errors"] = errors
    if errors:
        set_request_status(result_request, ResultRequestStatus.FAILED, "; ".join(errors))
        return None
    progress.setdefault("submitted_at", timezone.localtime().isoformat())
    result_request.is_submitted = True
    set_request_status(result_request, ResultRequestStatus.SUBMITTED)

    return None


def process_metsights_order(result_request: ResultRequest, provider_api_data: dict) -> str | None:
    error = submit_metsights_request(result_request, provider_api_data)
    if error:
        return error
    if result_request.status != ResultRequestStatus.SUBMITTED:
        return None
    return handle_metsights_report_fetch(result_request, provider_api_data)

