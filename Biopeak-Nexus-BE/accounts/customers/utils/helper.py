from django.conf import settings
from requests import ConnectionError, Response, Session, Timeout
from requests.exceptions import JSONDecodeError

from accounts.customers.models import CustomerCopilotSession, CustomerProfile
from core.utils.exceptions import ServiceUnavailable
from core.utils.log import logger

ASK_AI_BASE_URL = "https://ask-ai.biopeak.com"


def get_ask_ai_response_data(response: Response) -> dict:
    response_context = (
        f"endpoint={response.url} status={response.status_code} "
        f"content_type={response.headers.get('Content-Type', '')} "
        f"elapsed_seconds={response.elapsed.total_seconds()}"
    )
    if not response.ok:
        logger.error(f"ASK-AI request failed: {response_context} reason=upstream_http_error")
        raise ServiceUnavailable("ASK-AI is unavailable.")
    try:
        response_data = response.json()
    except JSONDecodeError:
        logger.error(f"ASK-AI request failed: {response_context} reason=invalid_json")
        raise ServiceUnavailable("ASK-AI returned an invalid response.") from None
    if not isinstance(response_data, dict):
        logger.error(f"ASK-AI request failed: {response_context} reason=expected_json_object")
        raise ServiceUnavailable("ASK-AI returned incomplete credentials.")
    session_id = response_data.get("session_id")
    token = response_data.get("token")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 255:
        logger.error(f"ASK-AI request failed: {response_context} reason=invalid_or_missing_session_id")
        raise ServiceUnavailable("ASK-AI returned an invalid session ID.")
    if not isinstance(token, str) or not token:
        logger.error(f"ASK-AI request failed: {response_context} reason=invalid_or_missing_token")
        raise ServiceUnavailable("ASK-AI returned incomplete credentials.")
    return response_data


def register_copilot_client(customer_profile: CustomerProfile) -> dict:
    logging_context = f"operation=register customer_profile={customer_profile.pk} endpoint=/clients/register/"
    if not settings.ASK_AI_API_KEY:
        logger.error(f"ASK-AI request failed: {logging_context} reason=missing_api_key")
        raise ServiceUnavailable("ASK-AI is not configured.")
    logger.info(f"ASK-AI request started: {logging_context}")
    session = Session()
    session.headers.update({"X-API-KEY": settings.ASK_AI_API_KEY})
    try:
        response = session.post(
            f"{ASK_AI_BASE_URL}/clients/register/",
            json={"client_id": str(customer_profile.pk)},
            timeout=30,
        )
    except (ConnectionError, Timeout) as error:
        logger.error(
            f"ASK-AI request failed: {logging_context} "
            f"reason=connection_or_timeout error_type={type(error).__name__}",
            exc_info=True,
        )
        raise ServiceUnavailable("ASK-AI registration is unavailable.") from None
    finally:
        session.close()
    return get_ask_ai_response_data(response)


def get_copilot_session_token(session_id: str) -> dict:
    logging_context = "operation=token endpoint=/clients/token/"
    if not settings.ASK_AI_API_KEY:
        logger.error(f"ASK-AI request failed: {logging_context} reason=missing_api_key")
        raise ServiceUnavailable("ASK-AI is not configured.")
    logger.info(f"ASK-AI request started: {logging_context}")
    session = Session()
    session.headers.update({"X-API-KEY": settings.ASK_AI_API_KEY})
    try:
        response = session.post(
            f"{ASK_AI_BASE_URL}/clients/token/",
            json={"session_id": session_id},
            timeout=30,
        )
    except (ConnectionError, Timeout) as error:
        logger.error(
            f"ASK-AI request failed: {logging_context} "
            f"reason=connection_or_timeout error_type={type(error).__name__}",
            exc_info=True,
        )
        raise ServiceUnavailable("ASK-AI token issuance is unavailable.") from None
    finally:
        session.close()
    return get_ask_ai_response_data(response)


def initialize_customer_chat_session(
        customer_profile: CustomerProfile,
) -> tuple[CustomerCopilotSession, str]:
    chat_session, _ = CustomerCopilotSession.objects.get_or_create(
        customer_profile=customer_profile
    )
    if chat_session.session_id:
        response_data = get_copilot_session_token(chat_session.session_id)
        return chat_session, response_data.get("token")
    response_data = register_copilot_client(customer_profile)
    chat_session.session_id = response_data.get("session_id")
    chat_session.save(update_fields=["session_id", "updated_at"])
    return chat_session, response_data.get("token")
