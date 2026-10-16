"""Submit BugSpeaks gut microbiome orders from saved booking dictionaries."""

from core.utils.log import logger
from integrations.bugspeaks.utils.sdk import register_bugspeaks_client
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus


def handle_bugspeaks_gut_microbiome_booking(result_request: ResultRequest, request=None) -> tuple | None:
    if result_request.data.get("bugspeaks_id"):
        result_request.is_submitted = True
        result_request.save(update_fields=["is_submitted", "updated_at"])
        result_request.status = ResultRequestStatus.PENDING
        return True, None
    configuration = result_request.product.provider.api.data or {}
    booking = result_request.data or {}
    profile = result_request.profile_data or {}
    required_values = {
        "api_key": configuration.get("api_key"), "kit_id": booking.get("kit_id"),
    }
    missing_keys = [key for key, value in required_values.items() if value is None or value == ""]
    if missing_keys:
        result_request.failure_detail = f"Missing BugSpeaks booking values: {', '.join(missing_keys)}."
        logger.error(f"BugSpeaks booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    if not isinstance(required_values["kit_id"], str):
        result_request.failure_detail = "BugSpeaks kit_id must be a string."
        logger.error(f"BugSpeaks booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    full_name = profile.get("full_name")
    if full_name is not None and not isinstance(full_name, str):
        result_request.failure_detail = "BugSpeaks full_name must be a string when supplied."
        logger.error(f"BugSpeaks booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    name_parts = (full_name or "").strip().split(maxsplit=1)
    first_name, last_name = (name_parts + [None, None])[:2]
    optional_values = {"full_name": full_name, "email": profile.get("email"), "phone": profile.get("phone")}
    missing_optional_keys = [key for key, value in optional_values.items() if value is None]
    if missing_optional_keys:
        logger.warning(f"BugSpeaks booking continuing: request={result_request.pk} missing_optional_keys={missing_optional_keys}")
    response, error = register_bugspeaks_client(
        api_key=required_values["api_key"], bugspeaks_id=required_values["kit_id"],
        first_name=first_name or "-", last_name=last_name or "-",
        email=optional_values["email"] or "-", phone=optional_values["phone"] or "-",
        address="-", pincode="-",
    )
    if error is not None:
        error_detail = (error.get("message") or error.get("detail")) if isinstance(error, dict) else error
        result_request.failure_detail = str(error_detail or error or "BugSpeaks client-kit-assignment was not accepted.")
        logger.error(f"BugSpeaks booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    if not isinstance(response, dict):
        result_request.failure_detail = "BugSpeaks booking returned no valid response."
        logger.error(f"BugSpeaks booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    identifier = response.get("Bugspeaks_ID")
    if not identifier:
        result_request.failure_detail = "BugSpeaks booking response has no Bugspeaks_ID."
        logger.error(f"BugSpeaks booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    result_request.refresh_from_db(fields=["data", "status"])
    if result_request.status == ResultRequestStatus.CANCELLED:
        return None
    result_request.data = {**(result_request.data or {}), "bugspeaks_id": identifier}
    result_request.is_submitted = True
    result_request.save(update_fields=["data", "is_submitted", "updated_at"])
    result_request.status = ResultRequestStatus.PENDING
    return True, None
