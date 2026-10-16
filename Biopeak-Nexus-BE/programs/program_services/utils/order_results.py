"""Dispatch order report retrieval to the selected provider integration."""

from integrations.bugspeaks.utils.results import fetch_bugspeaks_order_reports
from integrations.strand_genomics.utils.results import (
    fetch_strand_nutri_dna_order_reports,
    fetch_strand_ghi_order_reports
)
from products.utils.constants import ProviderCallbackFunction, ProductCallbackFunction

PROVIDER_ORDER_REPORT_HANDLERS = {
    ProviderCallbackFunction.BUGSPEAKS: {
        ProductCallbackFunction.GUT_MICROBIOME: fetch_bugspeaks_order_reports,
    },
    ProviderCallbackFunction.STRAND_LIFE_SCIENCES: {
        ProductCallbackFunction.GENOMICS_NUTRI_DNA: fetch_strand_nutri_dna_order_reports,
        ProductCallbackFunction.GENOMICS_HEALTH_INSIGHTS: fetch_strand_ghi_order_reports,
    },
}


def fetch_order_reports(result_request):
    provider_handlers = PROVIDER_ORDER_REPORT_HANDLERS.get(result_request.product.provider.callback) or {}
    handler = provider_handlers.get(result_request.product.callback)
    if not handler:
        return None, "Order report retrieval is not supported for this provider."
    return handler(result_request)
