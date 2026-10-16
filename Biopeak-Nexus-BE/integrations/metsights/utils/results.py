"""Retrieve and persist MetSights report data and documents."""

from math import ceil
from pathlib import Path

from integrations.metsights.utils.sdk import (
    download_external_file,
    get_consolidated_precision_report,
    get_files_for_report,
    get_health_risk_landscape_report,
    get_lifestyle_blueprint_report,
    get_metsights_report,
    get_supplement_blueprint_report,
    get_trends_for_report,
)
from integrations.metsights.utils.db import (
    get_existing_report_document,
    get_metsights_result,
    save_report_data,
    save_report_document,
    save_report_file_data,
)
from programs.services.models import ResultRequest, ServiceDocument
from programs.services.utils.constants import ResultRequestStatus, ServiceDocumentCategory, ServiceReportComponent

REPORT_DOCUMENT_HANDLERS = {
    "health-risk-landscape": get_health_risk_landscape_report,
    "lifestyle-blueprint": get_lifestyle_blueprint_report,
    "supplement-blueprint": get_supplement_blueprint_report,
    "consolidated": get_consolidated_precision_report,
}
DOCUMENT_CATEGORIES = dict.fromkeys(
    [".json", ".vcf", ".csv", ".xls", ".xlsx"], ServiceDocumentCategory.RAW,
)
REPORT_COMPONENTS = {
    "health-risk-landscape": ServiceReportComponent.METSIGHTS_HEALTH_RISK_LANDSCAPE,
    "lifestyle-blueprint": ServiceReportComponent.METSIGHTS_LIFESTYLE_BLUEPRINT,
    "supplement-blueprint": ServiceReportComponent.METSIGHTS_SUPPLEMENT_BLUEPRINT,
    "consolidated": ServiceReportComponent.METSIGHTS_CONSOLIDATED,
}


def fetch_and_save_document(
    result_request: ResultRequest, artifact: dict, replace_existing: bool,
) -> tuple[ServiceDocument | None, str | None]:
    artifacts = result_request.data.setdefault("artifacts", {})
    identifier = artifacts.get(artifact["key"])
    if identifier and not replace_existing:
        document = get_existing_report_document(result_request, identifier)
        if document:
            return document, None
    (downloaded_file, content_type), error = download_external_file(artifact["file"])
    if downloaded_file is None or content_type is None:
        return None, error
    with downloaded_file:
        document = save_report_document(
            result_request, artifact, downloaded_file, content_type
        )
    if document is None:
        return None, "MetSights returned an empty file."
    artifacts[artifact["key"]] = str(document.pk)
    return document, None


def _has_saved_report_data(
        result_request: ResultRequest, key: str, replace_existing: bool
) -> bool:
    if replace_existing:
        return False
    result = get_metsights_result(result_request)
    if result is None:
        return False
    return (result.data or {}).get(key) is not None


def fetch_metsights_analysis(
    result_request: ResultRequest, api_key: str, record_id: str, replace_existing: bool,
) -> list[str]:
    if _has_saved_report_data(result_request, "analysis_data", replace_existing):
        return []
    payload, error = get_metsights_report(report_id=record_id, api_key=api_key)
    if error:
        return [f"analysis: {error}"]
    analysis = payload.pop("data", None)
    if analysis is None:
        return ["analysis: not available"]
    save_report_data(result_request, "report_data", payload, replace_existing)
    save_report_data(result_request, "analysis_data", analysis, replace_existing)
    return []


def fetch_metsights_report_documents(
    result_request: ResultRequest, api_key: str, record_id: str, replace_existing: bool,
) -> list[str]:
    errors = []
    for component, fetch_report in REPORT_DOCUMENT_HANDLERS.items():
        identifier = result_request.data.get("artifacts", {}).get(component)
        if identifier and not replace_existing and get_existing_report_document(result_request, identifier):
            continue
        payload, error = fetch_report(report_id=record_id, api_key=api_key)
        if error:
            errors.append(f"{component}: {error}")
            continue
        if not payload.get("file"):
            errors.append(f"{component}: not available")
            continue
        artifact = {
            "key": component,
            "report_component": REPORT_COMPONENTS[component],
            "file": payload["file"],
            "filename": f"MetSights_{component}_{record_id}.pdf",
            "category": ServiceDocumentCategory.REPORT,
        }
        document, error = fetch_and_save_document(result_request, artifact, replace_existing)
        if error:
            errors.append(f"{component}: {error}")
    return errors


def _save_report_files(result_request: ResultRequest, remote_files: list[dict], replace_existing: bool) -> list[str]:
    errors = []
    for remote_file in remote_files:
        identifier = str(remote_file["id"])
        if not remote_file["file"]:
            errors.append(f"file:{identifier}: not available")
            continue
        filename = remote_file.get("name") or f"MetSights_{identifier}.pdf"
        artifact = {
            "key": f"file:{identifier}",
            "file": remote_file["file"],
            "filename": filename,
            "category": DOCUMENT_CATEGORIES.get(Path(filename).suffix.lower(), ServiceDocumentCategory.REPORT),
        }
        document, error = fetch_and_save_document(result_request, artifact, replace_existing)
        if error:
            errors.append(f"file:{identifier}: {error}")
            continue
        if document is None:
            return errors
        if remote_file.get("metadata") is None:
            continue
        save_report_file_data(result_request, identifier, remote_file["metadata"], replace_existing)
    return errors


def fetch_metsights_report_files(
    result_request: ResultRequest, api_key: str, record_id: str, replace_existing: bool,
) -> list[str]:
    first_page, error = get_files_for_report(report_id=record_id, api_key=api_key, page=1)
    if error:
        return [f"files: {error}"]
    errors = _save_report_files(result_request, first_page["data"], replace_existing)
    pages = max(1, ceil(first_page["count"] / max(len(first_page["data"]), 1)))
    for page_number in range(2, pages + 1):
        page, error = get_files_for_report(report_id=record_id, api_key=api_key, page=page_number)
        if error:
            errors.append(f"files page {page_number}: {error}")
            continue
        errors.extend(_save_report_files(result_request, page["data"], replace_existing))
    return errors


def fetch_metsights_trends(
    result_request: ResultRequest, api_key: str, record_id: str, replace_existing: bool,
) -> list[str]:
    if _has_saved_report_data(result_request, "trends_data", replace_existing):
        return []
    trends, error = get_trends_for_report(report_id=record_id, api_key=api_key)
    if error:
        return [f"trends: {error}"]
    save_report_data(result_request, "trends_data", trends, replace_existing)
    return []


def _get_fetch_status(result_request: ResultRequest, errors: list[str]) -> str:
    if not errors:
        return ResultRequestStatus.COMPLETED
    result = get_metsights_result(result_request)
    if result is None:
        return ResultRequestStatus.PENDING
    data = result.data or {}
    if any(data.get(key) is not None for key in ["analysis_data", "trends_data"]):
        return ResultRequestStatus.PARTIALLY_FETCHED
    if data.get("files_data") or result.documents.filter(is_active=True).exists():
        return ResultRequestStatus.PARTIALLY_FETCHED
    return ResultRequestStatus.PENDING


def handle_metsights_report_fetch(
    result_request: ResultRequest, provider_api_data: dict, replace_existing: bool = False,
) -> None:
    api_key: str = provider_api_data.get("api_key") or ""
    record_id: str = result_request.data.get("record_id") or ""
    if not api_key or not record_id:
        result_request.status = ResultRequestStatus.FAILED
        result_request.failure_detail = "MetSights api_key or record_id is missing."
        return
    errors = []
    for fetch_handler in (
        fetch_metsights_analysis,
        fetch_metsights_report_documents,
        fetch_metsights_report_files,
        fetch_metsights_trends,
    ):
        errors += fetch_handler(result_request, api_key, record_id, replace_existing)
    result_request.data["fetch_errors"] = errors
    result_request.status = _get_fetch_status(result_request, errors)
    result_request.failure_detail = "; ".join(errors)
