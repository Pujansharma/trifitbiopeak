from django.urls import path

from compliance.consent_journey.views import (
    AcceptConsentFormView,
    ConsentFormUploadView,
    ConsentHistoryDetailView,
    ConsentHistoryListView,
    LatestConsentFormView,
    LatestConsentHistoryView,
    UpdateMarketingConsentView,
)

urlpatterns = [
    path("upload-consent-form/", ConsentFormUploadView.as_view()),
    path("latest-consent-form/", LatestConsentFormView.as_view()),
    path(
        "latest-consent-history/<uuid:customer_profile_id>/",
        LatestConsentHistoryView.as_view(),
    ),
    path(
        "consent-history/<uuid:customer_profile_id>/consent/<uuid:consent_id>/",
        ConsentHistoryDetailView.as_view(),
    ),
    path(
        "consent-history/<uuid:customer_profile_id>/",
        ConsentHistoryListView.as_view(),
    ),
    path(
        "accept-consent-form/<uuid:customer_profile_id>/",
        AcceptConsentFormView.as_view(),
    ),
    path(
        "update-MAC-consent/<uuid:customer_profile_id>/",
        UpdateMarketingConsentView.as_view(),
    ),
]
