from django.urls import path

from . import views

urlpatterns = [
    path('', views.SMSWebhookView.as_view()),
]
