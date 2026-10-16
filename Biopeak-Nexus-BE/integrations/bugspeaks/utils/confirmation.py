from rest_framework import serializers

from programs.services.models import ResultRequest


def bugspeaks_confirm_booking_handler(result_request: ResultRequest, attributes: dict) -> dict:
    if not (result_request.product.provider.api.data or {}).get("api_key"):
        raise serializers.ValidationError({"provider": "An api_key is required."})
    kit_identifier = result_request.data.get("kit_id")
    if not isinstance(kit_identifier, str) or not kit_identifier.strip():
        raise serializers.ValidationError({"data": "A non-empty kit_id string is required."})
    full_name = (result_request.profile_data or {}).get("full_name")
    if full_name is not None and not isinstance(full_name, str):
        raise serializers.ValidationError({"profile_data": "full_name must be a string."})
    return attributes
