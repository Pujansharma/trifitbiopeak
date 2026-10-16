"""BugSpeaks lifecycle metadata from stored provider callbacks."""

from django.db.models import Q

from core.utils.log import logger
from products.utils.constants import ProductCallbackFunction, ProviderCallbackFunction
from programs.composites.utils.db import update_composite_program_results_count
from programs.program_services.bookings import start_provider_fetch_task
from programs.program_services.utils.db import update_program_service_results_count
from programs.services.models import ResultRequest, ServiceResult
from programs.services.utils.constants import RequestResultType, ResultRequestStatus, ServiceDocumentType
from webhooks.bugspeaks.models import BugspeaksWebhook


def update_bugspeaks_lifecycle(result_request: ResultRequest, payload: dict, completed: bool = False) -> bool:
    result_request.refresh_from_db(fields=["data", "status"])
    if result_request.status == ResultRequestStatus.CANCELLED:
        return False
    request_data = result_request.data or {}
    request_data["bugspeaks_id"] = payload.get("Bugspeaks_ID") or payload.get("bugspeaks_id")
    result_request.data = request_data
    result_request.save(update_fields=["data", "updated_at"])
    service_result, created = ServiceResult.objects.get_or_create(
        result_request=result_request, document_type=ServiceDocumentType.BUGSPEAKS_REPORT,
        defaults={
            "program_service": result_request.program_service,
            "product": result_request.product,
            "provider_name": result_request.product.provider.name,
            "product_name": result_request.product.name,
            "result_mode": result_request.request_type,
            "created_by": result_request.created_by,
            "data": payload,
        },
    )
    service_result.data = payload
    service_result.save(update_fields=["data", "updated_at"])
    if created:
        update_program_service_results_count(result_request.program_service.pk)
        update_composite_program_results_count(result_request.program_service.program.pk)
    if completed:
        start_provider_fetch_task(result_request)
    return True


def complete_bugspeaks_webhook(result_request: ResultRequest, payload: dict) -> bool:
    return update_bugspeaks_lifecycle(result_request, payload, completed=True)


BUGSPEAKS_WEBHOOK_STATUS_HANDLERS = {
    "Client Assigned": update_bugspeaks_lifecycle,
    "Kit Dispatched": update_bugspeaks_lifecycle,
    "Kit Delivered": update_bugspeaks_lifecycle,
    "Request Delayed": update_bugspeaks_lifecycle,
    "Pick Up Requested": update_bugspeaks_lifecycle,
    "Pick Up Initiated": update_bugspeaks_lifecycle,
    "Sample Picked Up": update_bugspeaks_lifecycle,
    "Sample Received": update_bugspeaks_lifecycle,
    "QC Passed": update_bugspeaks_lifecycle,
    "QC Failed": update_bugspeaks_lifecycle,
    "Completed": complete_bugspeaks_webhook,
}


def handle_bugspeaks_webhook(payload: dict) -> tuple[bool | None, str | None]:
    if not isinstance(payload, dict):
        logger.warning("BugSpeaks webhook ignored: reason=invalid_payload")
        return None, "Invalid payload."
    identifier = payload.get("Bugspeaks_ID") or payload.get("bugspeaks_id")
    event = payload.get("Project_Status")
    if not isinstance(identifier, str) or not identifier or not isinstance(event, str):
        logger.warning("BugSpeaks webhook ignored: reason=unknown_event_or_identifier")
        return None, "Unknown event or identifier."
    handler = BUGSPEAKS_WEBHOOK_STATUS_HANDLERS.get(event)
    if not handler:
        logger.warning(f"BugSpeaks webhook ignored: identifier={identifier} reason=unknown_event event={event}")
        return None, "Unknown event or identifier."
    result_request = ResultRequest.objects.filter(
        Q(data__bugspeaks_id__iexact=identifier) | Q(data__kit_id__iexact=identifier),
        product__provider__callback=ProviderCallbackFunction.BUGSPEAKS,
        product__callback=ProductCallbackFunction.GUT_MICROBIOME,
        request_type=RequestResultType.ORDER,
        is_submitted=True,
    ).exclude(status=ResultRequestStatus.CANCELLED).first()
    if not result_request:
        logger.warning(f"BugSpeaks webhook ignored: identifier={identifier} reason=order_not_found")
        return None, "Order not found."
    logger.info(f"BugSpeaks lifecycle callback: request={result_request.pk} event={event}")
    return handler(result_request, payload), None


def get_bugspeaks_lifecycle(result_request: ResultRequest) -> dict | None:
    identifier = result_request.data.get("bugspeaks_id")
    if not identifier:
        return None
    webhook = BugspeaksWebhook.objects.filter(
        Q(data__Bugspeaks_ID__iexact=identifier) | Q(data__bugspeaks_id__iexact=identifier),
        data__Project_Status__in=list(BUGSPEAKS_WEBHOOK_STATUS_HANDLERS),
    ).first()
    if not webhook:
        return None
    return {"event": webhook.data["Project_Status"], "received_at": webhook.created_at}
