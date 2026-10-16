from products.utils.constants import ProductCallbackFunction
from integrations.five_c_networks.utils.results import handle_evo_report_fetch

FIVE_C_NETWORK_HANDLER = {
    ProductCallbackFunction.EVO_360: handle_evo_report_fetch,
}
