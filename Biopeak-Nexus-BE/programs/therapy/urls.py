from django.urls import path

from programs.views import TherapyProgramPaymentView

from . import views

urlpatterns = [
    path("services/", views.TherapyProgramServicesView.as_view()),
    path("<uuid:pk>/", views.TherapyProgramDetailView.as_view()),
    path("<uuid:pk>/payments/", TherapyProgramPaymentView.as_view()),
    path(
        "<uuid:pk>/redeemable-centers/",
        views.TherapyProgramRedeemableCentersView.as_view(),
    ),
    path(
        "<uuid:pk>/available-redeemable-centers/",
        views.TherapyProgramAvailableRedeemableCentersView.as_view(),
    ),
    path(
        "<uuid:pk>/services/",
        views.TherapyProgramServicesListView.as_view(),
    ),
    path(
        "<uuid:pk>/available-services/",
        views.TherapyProgramAvailableServicesView.as_view(),
    ),
    path("<uuid:pk>/redeem/", views.TherapyProgramRedeemView.as_view()),
    path(
        "<uuid:pk>/cancel/",
        views.TherapyProgramCancelView.as_view(),
    ),
]
