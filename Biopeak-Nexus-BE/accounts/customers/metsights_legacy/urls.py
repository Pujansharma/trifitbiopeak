from django.urls import include, path

urlpatterns = [
    path("records/", include("accounts.customers.metsights_legacy.records.urls")),
]
