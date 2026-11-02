from django.urls import path

from appointments.views import booking

urlpatterns = [
    path(
        "<uuid:pk>/audit-logs/",
        booking.AppointmentAuditLogListView.as_view(),
    ),
]
