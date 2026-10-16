from django.urls import path, include

from accounts.customers import views
from accounts.customers.programs.views import CustomerDocumentTimelinesView, CustomerProgramServicesView
from accounts.customers.metsights_legacy.views import MetsightsRecordsView, MetsightsReportsView

urlpatterns = [
    path("addresses/", include("accounts.customers.addresses.urls")),
    path("center-assignments/", include("accounts.customers.center_assignments.urls")),
    path("v2/", views.CustomerLeadProfileView.as_view()),
    path("", views.CustomerProfilesListView.as_view()),
    path("<uuid:pk>/", views.CustomerProfileDetailView.as_view()),
    path("<uuid:pk>/metsights-profile/", views.CustomerMetsightsProfileView.as_view()),
    path("<uuid:pk>/program-services/", CustomerProgramServicesView.as_view()),
    path("<uuid:pk>/metsights-legacy/records/", MetsightsRecordsView.as_view()),
    path("<uuid:pk>/metsights-legacy/reports/", MetsightsReportsView.as_view()),
    path("<uuid:pk>/document-timelines/", CustomerDocumentTimelinesView.as_view()),
    path(
        "<uuid:pk>/documents/",
        views.CustomerProfileDocumentsListView.as_view(),
    ),
    path("<uuid:pk>/programs/", include('accounts.customers.programs.urls')),
    path("<uuid:pk>/associates/", views.CustomerAssociateListView.as_view()),
    path(
        "<uuid:pk>/available-associates/",
        views.CustomerAvailableAssociateView.as_view(),
    ),
    path("<uuid:pk>/link-associates/", views.CustomerLinkAssociateView.as_view()),
    path("<uuid:pk>/centers/", views.CustomerCenterListView.as_view()),
    path("<uuid:pk>/available-centers/", views.CustomerAvailableCenterView.as_view()),
    path("<uuid:pk>/link-centers/", views.CustomerCenterLinkView.as_view()),
    path("<uuid:pk>/addresses/", views.CustomerProfileAddressView.as_view()),
    path("<uuid:pk>/features/", views.CustomerProfileFeatureView.as_view()),
    path("<uuid:pk>/copilot-chat/", views.CustomerCopilotChatView.as_view()),
    path(
        "metsights-legacy/",
        include('accounts.customers.metsights_legacy.urls')
    ),
]
