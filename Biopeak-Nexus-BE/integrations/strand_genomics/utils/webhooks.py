"""Strand lifecycle metadata from stored provider callbacks."""


from core.utils.log import logger
from products.utils.constants import ProductCallbackFunction, ProviderCallbackFunction
from programs.composites.utils.db import update_composite_program_results_count
from programs.program_services.bookings import start_provider_fetch_task
from programs.program_services.utils.db import update_program_service_results_count
from programs.services.models import ResultRequest, ServiceResult
from programs.services.utils.constants import RequestResultType, ResultRequestStatus, ServiceDocumentType
from webhooks.strand_genomics.models import StrandGenomicsWebhook

STRAND_EVENTS = {"qc_started", "report_available"}
STRAND_WEBHOOK_DOCUMENT_TYPES = {
    ProductCallbackFunction.GENOMICS_NUTRI_DNA: ServiceDocumentType.GENETICS_NUTRI_DNA,
    ProductCallbackFunction.GENOMICS_HEALTH_INSIGHTS: ServiceDocumentType.GENETICS_HEALTH_INSIGHTS,
}


def handle_strand_genomics_webhook(payload: dict):
    if not isinstance(payload, dict):
        logger.warning("Strand webhook ignored: reason=invalid_payload")
        return None, "Invalid payload."
    identifier = payload.get("test_request_id")
    event = payload.get("event_type")
    if not isinstance(identifier, str) or not identifier or not isinstance(event, str) or event not in STRAND_EVENTS:
        logger.warning("Strand webhook ignored: reason=unknown_event_or_identifier")
        return None, "Unknown event or identifier."
    result_request = ResultRequest.objects.filter(
        product__provider__callback=ProviderCallbackFunction.STRAND_LIFE_SCIENCES,
        product__callback__in=list(STRAND_WEBHOOK_DOCUMENT_TYPES),
        request_type=RequestResultType.ORDER, data__request_id__iexact=identifier,
    ).exclude(status=ResultRequestStatus.CANCELLED).first()
    if not result_request:
        logger.warning(f"Strand webhook ignored: identifier={identifier} reason=order_not_found")
        return None, "Order not found."
    logger.info(f"Strand lifecycle callback: request={result_request.pk} event={event}")
    service_result, created = ServiceResult.objects.get_or_create(
        result_request=result_request,
        document_type=STRAND_WEBHOOK_DOCUMENT_TYPES[result_request.product.callback],
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
    if event == "report_available":
        start_provider_fetch_task(result_request)
    return True, None


def get_strand_lifecycle(result_request: ResultRequest):
    identifier = result_request.data.get("request_id")
    if not identifier:
        return None
    webhook = StrandGenomicsWebhook.objects.filter(
        data__test_request_id__iexact=identifier, data__event_type__in=list(STRAND_EVENTS),
    ).first()
    if not webhook:
        return None
    return {"event": webhook.data["event_type"], "received_at": webhook.created_at}
