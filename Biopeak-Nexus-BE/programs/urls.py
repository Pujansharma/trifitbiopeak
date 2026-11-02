from django.urls import path, include

from programs.program_services.views import ServiceDocumentDeleteView
from programs.views import ProgramAuditHistoryView, ProgramPaymentHistoryView

urlpatterns = [
    path("<uuid:pk>/history/", ProgramAuditHistoryView.as_view()),
    path("<uuid:pk>/payment-history/", ProgramPaymentHistoryView.as_view()),
    path("program-services/", include("programs.program_services.urls")),
    path(
        "program-result-documents/<uuid:pk>/",
        ServiceDocumentDeleteView.as_view(),
    ),
    path("composites/", include("programs.composites.urls")),
    path("therapy-programs/", include("programs.therapy.urls")),
    path("assessment-programs/", include("programs.assessment.urls")),
    path("consultation-programs/", include("programs.consultation.urls")),
]
