from django.urls import path

from wearables.views import HealthDashboardView, HealthDomainView

urlpatterns = [
    path("domain-summary/", HealthDashboardView.as_view(), name="health-domain-summary"),
    path("domain-summary/<str:domain>/", HealthDomainView.as_view(), name="health-domain-summary-detail"),
]
