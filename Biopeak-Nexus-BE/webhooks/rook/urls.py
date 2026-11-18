from django.urls import path

from webhooks.rook.views import rook_data_webhook

urlpatterns = [
    path("data/", rook_data_webhook, name="rook-data-webhook"),
]
