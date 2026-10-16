from rest_framework import serializers

from programs.services.models import ResultRequest


def strand_confirm_booking_handler(result_request: ResultRequest, attributes: dict) -> dict:
    configuration = result_request.product.provider.api.data or {}
    missing_credentials = [
        key for key in ["client_id", "client_secret", "refresh_token", "logged_user_email"]
        if not configuration.get(key)
    ]
    if missing_credentials:
        raise serializers.ValidationError({"provider": {"missing_credentials": missing_credentials}})
    confirm_fields = attributes["confirm_fields"]
    collection_date = serializers.DateField(input_formats=["%Y-%m-%d"]).run_validation(
        confirm_fields.get("sample_collection_date", serializers.empty),
    )
    confirm_fields["sample_collection_date"] = collection_date.isoformat()
    if not attributes.get("confirm_files", {}).get("consent_file"):
        raise serializers.ValidationError({"confirm_files": {"consent_file": "A consent file is required."}})
    booking = result_request.data or {}
    if not isinstance(booking.get("kit_id"), str) or not booking["kit_id"].strip():
        raise serializers.ValidationError({"data": "A non-empty kit_id string is required."})
    profile = result_request.profile_data or {}
    for key in ["full_name", "gender", "date_of_birth"]:
        if not isinstance(profile.get(key), str) or not profile[key].strip():
            raise serializers.ValidationError({"profile_data": {key: "A non-empty string is required."}})
    return attributes
