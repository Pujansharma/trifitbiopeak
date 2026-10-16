from rest_framework import serializers


def validate_configured_payload(
    field_name: str, payload: dict, configured_fields: list | set | None,
) -> dict:
    if not isinstance(payload, dict):
        raise serializers.ValidationError({field_name: "Expected an object."})
    configured_keys = configured_fields or []
    missing_keys = [key for key in configured_keys if key not in payload]
    if missing_keys:
        raise serializers.ValidationError({field_name: {"missing": missing_keys}})
    return {key: payload[key] for key in configured_keys}
