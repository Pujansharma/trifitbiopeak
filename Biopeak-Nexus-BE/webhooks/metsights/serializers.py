from rest_framework import serializers

from core.utils.serializers import BaseSerializer
from integrations.metsights.tasks import start_metsights_fetch_task
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus, RequestResultType
from webhooks.metsights.utils.notifications import (
    send_metsights_file_upload_notification,
)
from webhooks.metsights.tasks import send_reports_export_email

REPORTS_EXPORT_SCOPE = "reports.export"
RECORDS_FILES_UPLOAD = "files.upload"
REPORTS_AVAILABLE_SCOPE = "reports.available"


class MetsightsWebhookSerializer(BaseSerializer):
    payload = serializers.JSONField(required=False, write_only=True)

    def create(self, validated_data: dict) -> bool:
        payload = validated_data.get("payload") or {}
        if not isinstance(payload, dict):
            return True
        scope = payload.get("scope")
        data = payload.get("data", {}) or {}
        if not isinstance(data, dict):
            return True
        record_id = data.get("record_id")
        if scope == RECORDS_FILES_UPLOAD:
            record = data.get("record") or {}
            record_id = record.get("id") if isinstance(record, dict) else None
        supported_callback = scope in [REPORTS_EXPORT_SCOPE, RECORDS_FILES_UPLOAD]
        if scope == REPORTS_AVAILABLE_SCOPE:
            supported_callback = data.get("status") == "available"
        if supported_callback and isinstance(record_id, str) and record_id:
            result_request = ResultRequest.objects.filter(
                program_service__data__record_id=record_id,
                request_type=RequestResultType.ORDER,
            ).exclude(
                status=ResultRequestStatus.CANCELLED
            ).first()
            if result_request:
                start_metsights_fetch_task(result_request)

        if scope == REPORTS_EXPORT_SCOPE:
            data = payload.get("data", {}) or {}
            if not isinstance(data, dict):
                return True
            profile = data.get("profile", {}) or {}
            first_name = profile.get("first_name", "")
            files = data.get("files", [])
            send_reports_export_email(data.get("email"), first_name, files)
        if scope == RECORDS_FILES_UPLOAD:
            # print("PAYLOAD: ", json.dumps(payload, indent=2))
            data = payload.get("data", {}) or {}
            if not isinstance(data, dict):
                return True
            send_metsights_file_upload_notification(data)

        return True
