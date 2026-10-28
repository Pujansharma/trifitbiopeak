from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from accounts.customers.models import CustomerProfile
from accounts.utils.permissions import IsAdminUser, IsCustomerUser
from compliance.consent_journey.models import ConsentForm, CustomerConsentHistory
from compliance.consent_journey.serializers import (
    AcceptConsentFormSerializer,
    ConsentFormDetailSerializer,
    ConsentFormUploadSerializer,
    ConsentHistoryDetailSerializer,
    ConsentHistoryListItemSerializer,
    UpdateMarketingConsentSerializer,
)
from compliance.consent_journey.utils.db import (
    build_latest_consent_history_map,
    get_consent_history_queryset,
    get_latest_consent_form,
    get_latest_consent_history_rows,
)
from core.utils.exceptions import get_object_or_404
from core.utils.views import BaseCreateAPIView, BaseGenericAPIView, BaseListAPIView
from core.utils.views.mixin import GetMethodMixin, PostMethodMixin


class ConsentFormUploadView(BaseCreateAPIView):
    permission_classes = [IsAdminUser]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = ConsentFormUploadSerializer
    queryset = ConsentForm.objects.all()
    create_success_message = "Consent form uploaded."


class OwnedCustomerProfileMixin:
    def get_customer_profile(self):
        return get_object_or_404(
            CustomerProfile.objects.filter(customer=self.request.user.customer),
            "Customer profile not found.",
            pk=self.kwargs["customer_profile_id"],
        )


class AcceptConsentFormView(OwnedCustomerProfileMixin, BaseGenericAPIView, PostMethodMixin):
    permission_classes = [IsCustomerUser]
    parser_classes = [JSONParser]
    serializer_class = AcceptConsentFormSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["customer_profile"] = self.get_customer_profile()
        return context

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Consent form accepted.", status=201)


class UpdateMarketingConsentView(
    OwnedCustomerProfileMixin, BaseGenericAPIView, PostMethodMixin
):
    permission_classes = [IsCustomerUser]
    parser_classes = [JSONParser]
    serializer_class = UpdateMarketingConsentSerializer

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["customer_profile"] = self.get_customer_profile()
        return context

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return self.send_response("Marketing consent updated.", status=201)


class LatestConsentFormView(BaseGenericAPIView, GetMethodMixin):
    permission_classes = [IsCustomerUser]

    def get(self, request, *args, **kwargs):
        latest = get_latest_consent_form()
        if latest is None:
            raise NotFound("No consent form has been uploaded.")
        consent_form_data = ConsentFormDetailSerializer(latest).data
        return self.send_response(
            "Latest consent form.",
            {
                "consent_form_url": consent_form_data["consent_form_url"],
                "consent_form_version": consent_form_data["version"],
            },
        )


class LatestConsentHistoryView(OwnedCustomerProfileMixin, BaseGenericAPIView, GetMethodMixin):
    permission_classes = [IsCustomerUser]

    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        rows = get_latest_consent_history_rows(customer_profile)
        if rows is None:
            raise NotFound("No consent history found.")
        return self.send_response(
            "Latest consent history.",
            build_latest_consent_history_map(rows),
        )


class ConsentHistoryListView(OwnedCustomerProfileMixin, BaseListAPIView):
    permission_classes = [IsCustomerUser]
    serializer_class = ConsentHistoryListItemSerializer
    pagination_class = None
    list_success_message = "Consent history."

    def get_queryset(self):
        return get_consent_history_queryset(self.get_customer_profile())


class ConsentHistoryDetailView(OwnedCustomerProfileMixin, BaseGenericAPIView, GetMethodMixin):
    permission_classes = [IsCustomerUser]

    def get(self, request, *args, **kwargs):
        customer_profile = self.get_customer_profile()
        history = get_object_or_404(
            CustomerConsentHistory.objects.filter(
                customer_profile=customer_profile
            ).select_related("consent_form_version"),
            "Consent history not found.",
            pk=self.kwargs["consent_id"],
        )
        return self.send_response(
            "Consent history details.",
            ConsentHistoryDetailSerializer(history).data,
        )
