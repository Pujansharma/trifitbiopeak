"""Resolve provider/product booking workers accepting a saved ResultRequest.

Pending order creation stores provider inputs. Confirmation starts the worker.
Each worker owns its input checks and provider submission, logging and returning
None when it cannot proceed.
"""

from integrations.bugspeaks.utils.booking import handle_bugspeaks_gut_microbiome_booking
from integrations.strand_genomics.utils.booking import (
    strand_genomic_health_insights_booking,
    strand_nutri_dna_booking,
)
from products.utils.constants import ProductCallbackFunction, ProviderCallbackFunction

PROVIDER_REPORT_REQUEST_HANDLER = {
    ProviderCallbackFunction.BUGSPEAKS: {
        ProductCallbackFunction.GUT_MICROBIOME: handle_bugspeaks_gut_microbiome_booking,
    },
    ProviderCallbackFunction.STRAND_LIFE_SCIENCES: {
        ProductCallbackFunction.GENOMICS_NUTRI_DNA: strand_nutri_dna_booking,
        ProductCallbackFunction.GENOMICS_HEALTH_INSIGHTS: strand_genomic_health_insights_booking,
    },
}


def get_report_request_handler(provider_callback: str, product_callback: str):
    provider_handlers = PROVIDER_REPORT_REQUEST_HANDLER.get(provider_callback) or {}
    return provider_handlers.get(product_callback)
