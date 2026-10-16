from products.utils.constants import ProductCallbackFunction
from integrations.orange_labs.utils.results import handle_orange_report_fetch

ORANGE_LABS_HANDLER = {
    ProductCallbackFunction.BLOOD: handle_orange_report_fetch,
}
