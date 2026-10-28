from django.urls import include, path

urlpatterns = [
    path("consent-journey/", include("compliance.consent_journey.urls")),
]
