from products.utils.constants import ProductCallbackFunction

from integrations.metsights.utils.results import handle_metsights_report_fetch

METSIGHTS_HANDLER = {
    ProductCallbackFunction.METSIGHTS_PP: handle_metsights_report_fetch,
}
