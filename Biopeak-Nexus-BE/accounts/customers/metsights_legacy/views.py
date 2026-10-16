from accounts.customers.metsights_legacy.utils.helper import (
    get_metsights_records_for_customer,
    get_metsights_reports_for_customer,
)
from accounts.customers.views import CustomerProfileMeta
from accounts.utils.permissions import IsAdminUser, IsAssociateUser, IsCustomerUser


class MetsightsLegacyViewMeta(CustomerProfileMeta):
    permission_classes = [IsAdminUser | IsAssociateUser | IsCustomerUser]


class MetsightsRecordsView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer = self.get_customer_profile()
        data = get_metsights_records_for_customer(customer)
        if data is None:
            return self.send_response("MetSights records not found.", status=404)
        return self.send_response("MetSights records fetched.", data=data)


class MetsightsReportsView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer = self.get_customer_profile()
        subscription_id = request.query_params.get("subscription")
        data = get_metsights_reports_for_customer(
            customer,
            subscription_id=subscription_id,
        )
        if data is None:
            return self.send_response("MetSights reports not found.", status=404)
        return self.send_response("MetSights reports fetched.", data=data)
