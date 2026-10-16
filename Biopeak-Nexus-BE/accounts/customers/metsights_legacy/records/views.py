from accounts.customers.metsights_legacy.utils.helper import (
    export_metsights_reports_for_customer,
    get_metsights_attachments_for_customer,
    get_metsights_consolidated_report_for_customer,
    get_metsights_personalised_plan_for_customer,
    get_metsights_record_for_customer,
    get_metsights_report_files_for_customer,
    get_metsights_report_for_customer,
    get_metsights_trends_for_customer,
)
from accounts.customers.metsights_legacy.views import MetsightsLegacyViewMeta
from accounts.customers.programs.serializers import CustomerDocumentExportSerializer


class MetsightsRecordView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_record_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights record not found.", status=404)
        return self.send_response("MetSights record fetched.", data=data)


class MetsightsRecordPersonalisedPlanView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_personalised_plan_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights personalised plan not found.", status=404)
        return self.send_response("MetSights personalised plan fetched.", data=data)


class MetsightsRecordAttachmentsView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        category_type = request.query_params.get("category_type")
        module_type = request.query_params.get("module_type")
        file_type = request.query_params.get("file_type")
        data = get_metsights_attachments_for_customer(
            customer_profiles,
            record_id,
            category_type=category_type,
            module_type=module_type,
            file_type=file_type,
        )
        if data is None:
            return self.send_response("MetSights record resource not found.", status=404)
        return self.send_response("MetSights record resource fetched.", data=data)


class MetsightsRecordReportView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_report_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights record resource not found.", status=404)
        return self.send_response("MetSights record resource fetched.", data=data)


class MetsightsRecordConsolidatedReportView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_consolidated_report_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights record resource not found.", status=404)
        return self.send_response("MetSights record resource fetched.", data=data)


class MetsightsRecordTrendsView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_trends_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights record resource not found.", status=404)
        return self.send_response("MetSights record resource fetched.", data=data)


class MetsightsRecordReportFilesView(MetsightsLegacyViewMeta):
    def get(self, request, *args, **kwargs):
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        data = get_metsights_report_files_for_customer(customer_profiles, record_id)
        if data is None:
            return self.send_response("MetSights record resource not found.", status=404)
        return self.send_response("MetSights record resource fetched.", data=data)


class MetsightsRecordExportView(MetsightsLegacyViewMeta):
    serializer_class = CustomerDocumentExportSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer_profiles = self.get_queryset()
        record_id = self.kwargs["pk"]
        email = serializer.validated_data["email"]
        response_data = export_metsights_reports_for_customer(customer_profiles, record_id, email)
        if response_data is None:
            return self.send_response("MetSights reports export could not be requested.", status=404)
        data = response_data.get("data")
        return self.send_response("Reports export request received.", data=data)
