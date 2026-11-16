from django.conf import settings

from core.utils.metadata import BaseMetadata
from leads.serializers import LeadOpsOnboardingEmailSerializer
from leads.utils.constants import OPS_ONBOARDING_EMAIL_TO


class LeadsMetadata(BaseMetadata):
    def determine_metadata(self, request, view):
        metadata = super().determine_metadata(request, view)
        metadata["ops_onboarding_email"] = {
            "to": list(OPS_ONBOARDING_EMAIL_TO),
            "from": settings.DEFAULT_FROM_EMAIL,
            "cc": "Authenticated user email (JWT)",
            "subject_template": (
                "New Client Onboarding | {client_name} | {package_name}"
            ),
            **self.get_serializer_info(LeadOpsOnboardingEmailSerializer()),
        }
        return metadata
