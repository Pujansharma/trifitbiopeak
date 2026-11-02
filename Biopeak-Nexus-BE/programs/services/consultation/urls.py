from django.urls import path

from programs.services.consultation import views

urlpatterns = [
    path("", views.ConsultationServicesView.as_view()),
    path("<uuid:pk>/", views.ConsultationServiceDetailView.as_view()),
]
