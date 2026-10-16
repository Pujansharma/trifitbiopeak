from django.urls import path

from . import views

urlpatterns = [
    path("<str:pk>/", views.MetsightsRecordView.as_view()),
    path("<str:pk>/personalised-plan/", views.MetsightsRecordPersonalisedPlanView.as_view()),
    path("<str:pk>/attachments/", views.MetsightsRecordAttachmentsView.as_view()),
    path("<str:pk>/report/", views.MetsightsRecordReportView.as_view()),
    path("<str:pk>/report/consolidated/", views.MetsightsRecordConsolidatedReportView.as_view()),
    path("<str:pk>/report/trends/", views.MetsightsRecordTrendsView.as_view()),
    path("<str:pk>/report/files/", views.MetsightsRecordReportFilesView.as_view()),
    path("<str:pk>/export-reports/", views.MetsightsRecordExportView.as_view()),
]
