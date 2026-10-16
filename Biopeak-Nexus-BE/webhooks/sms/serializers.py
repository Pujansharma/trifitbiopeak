from rest_framework import serializers

from core.utils.fields import PhoneNumberSerializerField
from core.utils.serializers import BaseModelSerializer
from webhooks.sms.models import SMSWebhook


class SMSWebhookSerializer(BaseModelSerializer):
    pluginsource = serializers.CharField(
        source="plugin_source", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    requestedAt = serializers.DateTimeField(
        source="requested_at", required=False, allow_null=True,
    )
    status = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
    )
    deliveryTime = serializers.DateTimeField(
        source="delivery_time", required=False, allow_null=True,
    )
    telNum = PhoneNumberSerializerField(source="phone")
    credit = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
    )
    senderId = serializers.CharField(
        source="sender_id", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    campaignName = serializers.CharField(
        source="campaign_name", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    route = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
    )
    campaign_pid = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
    )
    clientId = serializers.CharField(
        source="client_id", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    userId = serializers.CharField(
        source="user_id", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    ts = serializers.DateTimeField(
        source="timestamp", required=False, allow_null=True,
    )
    CRQID = serializers.CharField(
        source="crqid", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    requestId = serializers.CharField(
        source="request_id", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    UUID = serializers.CharField(
        source="sender_uuid", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    INMSID = serializers.CharField(
        source="inmsid", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    DLT_TE_ID = serializers.CharField(
        source="dlt_te_id", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    eventName = serializers.CharField(
        source="event_name", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    event = serializers.CharField(
        required=False, allow_null=True, allow_blank=True, trim_whitespace=False,
    )
    failureReason = serializers.CharField(
        source="failure_reason", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    smsLength = serializers.CharField(
        source="sms_length", required=False, allow_null=True, allow_blank=True,
        trim_whitespace=False,
    )
    upperCaseEventName = serializers.CharField(
        source="upper_case_event_name", required=False, allow_null=True,
        allow_blank=True, trim_whitespace=False,
    )
    dryRun = serializers.BooleanField(
        source="dry_run", required=False, allow_null=True,
    )

    class Meta:
        model = SMSWebhook
        fields = [
            "pluginsource", "requestedAt", "status", "deliveryTime", "telNum",
            "credit", "senderId", "campaignName", "route", "campaign_pid",
            "clientId", "userId", "ts", "CRQID", "requestId", "UUID", "INMSID",
            "DLT_TE_ID", "eventName", "event", "failureReason", "smsLength",
            "upperCaseEventName", "dryRun",
        ]
