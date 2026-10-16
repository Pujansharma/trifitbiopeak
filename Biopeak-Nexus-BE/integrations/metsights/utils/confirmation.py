from rest_framework import serializers

from integrations.metsights.models import MetsightsProfile
from integrations.metsights.utils.sdk import GENDER_MAPPING
from programs.services.models import ResultRequest


def metsights_confirm_booking_handler(result_request: ResultRequest, attributes: dict) -> dict:
    configuration = result_request.product.provider.api.data or {}
    missing_credentials = [key for key in ["api_key", "subscription_id"] if not configuration.get(key)]
    if missing_credentials:
        raise serializers.ValidationError({"provider": {"missing_credentials": missing_credentials}})
    service = result_request.program_service
    if (service.data or {}).get("record_id"):
        return attributes
    profile = service.program.customer_profile
    mapping = MetsightsProfile.objects.filter(customer_profile=profile).first()
    if (not mapping or not mapping.profile_id) and (not profile.date_of_birth or profile.gender not in GENDER_MAPPING):
        raise serializers.ValidationError("MetSights requires a birth date and a supported gender.")
    return attributes
