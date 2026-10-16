from core.utils.log import logger
from integrations.orange_labs.utils.db import (
    mark_orange_result_request_completed,
    mark_orange_result_request_failed,
    save_orange_result_data,
)
from integrations.orange_labs.utils.helper import process_orange_report_fetch
from programs.services.models import ResultRequest


def handle_orange_report_fetch(
        result_request: ResultRequest,
        provider_api_data: dict,
):
    """Fetch all OrangeHealth reports using the configured key and profile phone."""
    logger.info(
        f"OrangeHealth result fetch handler started: "
        f"result_request_id={result_request.pk}"
    )
    api_key = provider_api_data.get("api_key", "")
    if not api_key:
        mark_orange_result_request_failed(
            result_request=result_request,
            error_message="API key is missing in provider configuration",
        )
        return None

    profile_data = result_request.profile_data or {}
    phone = profile_data.get("phone", "")
    if not phone:
        mark_orange_result_request_failed(
            result_request=result_request,
            error_message="Phone not provided",
        )
        return None

    metadata, result_files, error = process_orange_report_fetch(
        api_key=api_key,
        phone=phone,
    )
    if error:
        mark_orange_result_request_failed(
            result_request=result_request,
            error_message=error,
        )
        return None

    if not result_files:
        mark_orange_result_request_failed(
            result_request=result_request,
            error_message="OrangeHealth report files were not available",
        )
        return None

    service_result = save_orange_result_data(
        metadata=metadata,
        result_files=result_files,
        result_request=result_request,
    )
    mark_orange_result_request_completed(result_request)
    logger.info(
        f"OrangeHealth result fetch handler completed: "
        f"result_request_id={result_request.pk} "
        f"service_result_id={service_result.pk}"
    )
    return None
