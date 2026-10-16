from django.db import models

from core.utils.fields import PhoneNumberField
from core.utils.models import BaseUUIDModel


class SMSWebhook(BaseUUIDModel):
    phone = PhoneNumberField()
    plugin_source = models.TextField(null=True, blank=True)
    requested_at = models.DateTimeField(null=True, blank=True)
    status = models.TextField(null=True, blank=True)
    delivery_time = models.DateTimeField(null=True, blank=True)
    credit = models.TextField(null=True, blank=True)
    sender_id = models.TextField(null=True, blank=True)
    campaign_name = models.TextField(null=True, blank=True)
    route = models.TextField(null=True, blank=True)
    campaign_pid = models.TextField(null=True, blank=True)
    client_id = models.TextField(null=True, blank=True)
    user_id = models.TextField(null=True, blank=True)
    timestamp = models.DateTimeField(null=True, blank=True)
    crqid = models.TextField(null=True, blank=True)
    request_id = models.TextField(null=True, blank=True)
    sender_uuid = models.TextField(null=True, blank=True)
    inmsid = models.TextField(null=True, blank=True)
    dlt_te_id = models.TextField(null=True, blank=True)
    event_name = models.TextField(null=True, blank=True)
    event = models.TextField(null=True, blank=True)
    failure_reason = models.TextField(null=True, blank=True)
    sms_length = models.TextField(null=True, blank=True)
    upper_case_event_name = models.TextField(null=True, blank=True)
    dry_run = models.BooleanField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.pk}"
