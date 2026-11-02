from django.urls import path

from programs.consultation import views as consultation_views
from programs.program_services import views

urlpatterns = [
    # Existing client URLs remain supported alongside the category aliases below.
    path(
        "consultation-documents/<uuid:pk>/",
        consultation_views.ConsultationDocumentDetailView.as_view(),
    ),
    path("result-requests/<uuid:pk>/", views.ResultRequestDetailView.as_view()),
    path("result-requests/<uuid:pk>/files/", views.ResultRequestFilesView.as_view()),
    path(
        "result-requests/<uuid:pk>/confirm-order/",
        views.ResultRequestConfirmOrderView.as_view(),
    ),
    path("result-requests/<uuid:pk>/refetch/", views.ResultRequestRefetchView.as_view()),
    path("result-requests/<uuid:pk>/cancel/", views.ResultRequestCancelView.as_view()),
    path("results/<uuid:pk>/", views.ServiceResultDetailView.as_view()),
    path("results/<uuid:pk>/documents/", views.ServiceResultDocumentsView.as_view()),

    # Therapy: assigned service details, cancellation, and center alignment.
    path(
        "therapy-services/<uuid:pk>/",
        views.TherapyProgramServiceDetailView.as_view(),
    ),
    path(
        "therapy-services/<uuid:pk>/cancel/",
        views.TherapyProgramServiceCancelView.as_view(),
    ),
    path(
        "therapy-services/<uuid:pk>/redeemable-centers/",
        views.TherapyProgramServiceRedeemableCentersView.as_view(),
    ),
    path(
        "therapy-services/<uuid:pk>/available-redeemable-centers/",
        views.TherapyProgramServiceAvailableRedeemableCentersView.as_view(),
    ),

    # Consultation: assigned service details, cancellation, and document uploads.
    path(
        "consultation-services/<uuid:pk>/documents/",
        consultation_views.ConsultationProgramServiceDocumentsView.as_view(),
    ),
    path(
        "consultation-services/documents/<uuid:pk>/",
        consultation_views.ConsultationDocumentDetailView.as_view(),
    ),
    path(
        "consultation-services/<uuid:pk>/",
        views.ConsultationProgramServiceDetailView.as_view(),
    ),
    path(
        "consultation-services/<uuid:pk>/cancel/",
        views.ConsultationProgramServiceCancelView.as_view(),
    ),

    # Assessment: assigned service details, cancellation, results, and file uploads.
    path(
        "assessment-services/<uuid:pk>/",
        views.AssessmentProgramServiceDetailView.as_view(),
    ),
    path(
        "assessment-services/<uuid:pk>/cancel/",
        views.AssessmentProgramServiceCancelView.as_view(),
    ),
    path(
        "assessment-services/<uuid:pk>/providers/",
        views.AssessmentProgramServiceProviders.as_view(),
    ),

    path(
        "assessment-services/<uuid:pk>/products/",
        views.AssessmentProgramServiceProducts.as_view(),
    ),

    # Upload documents flow: Results first, then files in them
    path(
        "assessment-services/<uuid:pk>/results/",
        views.AssessmentProgramServiceResultsView.as_view(),
    ),
    path(
        "assessment-services/<uuid:pk>/documents/",
        views.AssessmentProgramServiceDocumentsView.as_view(),
    ),

    # Order requests: Create a pending order, then confirm to submit to the provider
    path(
        "assessment-services/<uuid:pk>/request-report/",
        views.AssessmentServiceReportRequestView.as_view(),
    ),

    # Fetch existing provider reports, or list fetch and order requests
    path(
        "assessment-services/<uuid:pk>/result-requests/",
        views.AssessmentServiceResultRequestView.as_view(),
    ),

    # Individual data about the result requests
    path(
        "assessment-services/result-requests/<uuid:pk>/",
        views.ResultRequestDetailView.as_view(),
    ),
    path(
        "assessment-services/result-requests/<uuid:pk>/files/",
        views.ResultRequestFilesView.as_view(),
    ),
    path(
        "assessment-services/result-requests/<uuid:pk>/confirm-order/",
        views.ResultRequestConfirmOrderView.as_view(),
    ),
    path(
        "assessment-services/result-requests/<uuid:pk>/refetch/",
        views.ResultRequestRefetchView.as_view(),
    ),

    path(
        "assessment-services/result-requests/<uuid:pk>/cancel/",
        views.ResultRequestCancelView.as_view(),
    ),

    # Results section: Get result info and files in them
    path(
        "assessment-services/results/<uuid:pk>/",
        views.ServiceResultDetailView.as_view(),
    ),
    path(
        "assessment-services/results/<uuid:pk>/documents/",
        views.ServiceResultDocumentsView.as_view(),
    ),
    path(
        "assessment-services/documents/<uuid:pk>/",
        views.ServiceDocumentDeleteView.as_view(),
    ),
]
