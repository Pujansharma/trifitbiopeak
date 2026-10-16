"""Submit the MetSights report product from a saved order request."""

from core.utils.log import logger
from integrations.metsights.utils.submission import process_metsights_order
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus


def handle_metsights_report_request(result_request: ResultRequest, request=None):
    configuration = result_request.product.provider.api.data or {}
    required_values = {
        "api_key": configuration.get("api_key"),
        "subscription_id": configuration.get("subscription_id"),
    }
    missing_keys = [key for key, value in required_values.items() if value is None or value == ""]
    if missing_keys:
        result_request.failure_detail = f"Missing MetSights booking values: {', '.join(missing_keys)}."
        logger.error(f"MetSights booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    error = process_metsights_order(result_request, configuration)
    if error:
        result_request.failure_detail = error
        logger.error(f"MetSights booking failed: request={result_request.pk} reason={error}")
        return None
    if result_request.status == ResultRequestStatus.FAILED:
        logger.error(f"MetSights booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    return True, None
