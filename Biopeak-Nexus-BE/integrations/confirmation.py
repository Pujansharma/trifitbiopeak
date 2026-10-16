"""Validate confirmation inputs and queue a provider booking."""

from pathlib import Path

from django.db import transaction
from rest_framework import serializers

from core.utils.log import logger
from core.utils.serializers import BaseSerializer
from products.utils.constants import ProviderCallbackFunction
from programs.program_services.bookings import start_provider_submission_thread
from programs.program_services.utils.confirmation import CONFIRMATION_HANDLERS
from programs.program_services.utils.db import update_program_service_fetch_counts
from programs.program_services.utils.report_requests import get_report_request_handler
from programs.services.models import ResultRequestFile
from programs.services.utils.constants import ResultRequestStatus


class OrderConfirmationSerializer(BaseSerializer):
    confirm_fields = serializers.JSONField(required=False, default=dict)
    confirm_files = serializers.DictField(child=serializers.FileField(), required=False, default=dict)

    def _validate_configured_payload(self, field_name, payload, configured_fields):
        if not isinstance(payload, dict):
            raise serializers.ValidationError({field_name: "Expected an object."})
        configured_keys = configured_fields or []
        missing_keys = [key for key in configured_keys if key not in payload]
        if missing_keys:
            logger.warning(
                f"Order confirmation missing fields: result_request_id={self.instance.pk} "
                f"field={field_name} missing={missing_keys}"
            )
            raise serializers.ValidationError({field_name: {"missing": missing_keys}})
        return {key: payload[key] for key in configured_keys}

    def validate(self, attrs: dict) -> dict:
        provider = self.instance.product.provider
        if not get_report_request_handler(provider.callback, self.instance.product.callback):
            raise serializers.ValidationError("Ordering is not supported for this product.")
        if not getattr(provider, "api", None):
            raise serializers.ValidationError({"provider": "Provider API configuration is missing."})
        attrs["confirm_fields"] = self._validate_configured_payload(
            "confirm_fields", attrs.get("confirm_fields", {}), provider.confirm_order_fields,
        )
        attrs["confirm_files"] = self._validate_configured_payload(
            "confirm_files", attrs.get("confirm_files", {}), provider.confirm_order_file_fields,
        )
        handler = CONFIRMATION_HANDLERS.get(provider.callback)
        if not handler:
            raise serializers.ValidationError("Confirmation is not supported for this provider.")
        return handler(self.instance, attrs)

    def update(self, instance, validated_data):
        if instance.is_submitted or instance.status in [
            ResultRequestStatus.QUEUED,
            ResultRequestStatus.RUNNING
        ]:
            return instance
        with transaction.atomic():
            _data = instance.data or {}
            confirm_fields = validated_data.get("confirm_fields", {})
            if instance.product.provider.callback == ProviderCallbackFunction.METFLUX:
                confirm_fields = {"confirmation": confirm_fields}
            _data.update(confirm_fields)
            instance.data = _data
            for field_name, uploaded_file in validated_data.get("confirm_files", {}).items():
                request_file, created = ResultRequestFile.objects.get_or_create(
                    result_request=instance, field_name=field_name,
                    defaults={
                        "file": uploaded_file, "filename": Path(uploaded_file.name).name,
                        "content_type": uploaded_file.content_type or "application/octet-stream", "is_active": True,
                    },
                )
                if not created:
                    request_file.file = uploaded_file
                    request_file.filename = Path(uploaded_file.name).name
                    request_file.content_type = uploaded_file.content_type or "application/octet-stream"
                    request_file.is_active = True
                    request_file.save(update_fields=["file", "filename", "content_type", "is_active", "updated_at"])
            instance.failure_detail = ""
            instance.started_at = None
            instance.completed_at = None
            instance.status = ResultRequestStatus.QUEUED
            instance.save(update_fields=[
                "data", "is_submitted", "status", "failure_detail", "started_at", "completed_at", "updated_at",
            ])
            update_program_service_fetch_counts(instance.program_service.pk)
        handler = get_report_request_handler(instance.product.provider.callback, instance.product.callback)
        start_provider_submission_thread(instance, handler, request=self.context.get("request"))
        return instance
