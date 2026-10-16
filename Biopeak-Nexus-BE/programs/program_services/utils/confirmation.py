from integrations.bugspeaks.utils.confirmation import bugspeaks_confirm_booking_handler
from integrations.metsights.utils.confirmation import metsights_confirm_booking_handler
from integrations.strand_genomics.utils.confirmation import strand_confirm_booking_handler
from products.utils.constants import ProviderCallbackFunction


CONFIRMATION_HANDLERS = {
    ProviderCallbackFunction.BUGSPEAKS: bugspeaks_confirm_booking_handler,
    ProviderCallbackFunction.STRAND_LIFE_SCIENCES: strand_confirm_booking_handler,
    ProviderCallbackFunction.METFLUX: metsights_confirm_booking_handler,
}
