from django.urls import path

from . import views

urlpatterns = [
    path("", views.CustomerProgramsView.as_view()),
    path("summary/", views.CustomerProgramsSummaryView.as_view()),
    path("therapy-programs/summary/", views.CustomerTherapyProgramSummaryView.as_view()),
    path("assessment-programs/summary/", views.CustomerAssessmentProgramSummaryView.as_view()),
    path("consultation-programs/summary/", views.CustomerConsultationProgramSummaryView.as_view()),
    path("composite-programs/summary/", views.CustomerCompositeProgramSummaryView.as_view()),
    path("results/", views.CustomerMetsightsResultsView.as_view()),
    path("documents/export-email/", views.CustomerDocumentExportView.as_view()),
    path('therapy-programs/', views.CustomerTherapyProgramsView.as_view()),
    path(
        "therapy-programs/<uuid:program_pk>/services/",
        views.CustomerTherapyProgramServicesView.as_view(),
    ),
    path("composite-programs/", views.CustomerCompositeProgramsView.as_view()),
    path(
        "composite-program-services/",
        views.CustomerCompositeProgramServicesView.as_view(),
    ),
]
