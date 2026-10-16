from django.contrib import admin
from django.http import HttpRequest

from webhooks.sms.models import SMSWebhook


@admin.register(SMSWebhook)
class SMSWebhookAdmin(admin.ModelAdmin):
    readonly_fields = [
        "id", "is_active", "created_at", "updated_at", "phone", "plugin_source",
        "requested_at", "status", "delivery_time", "credit", "sender_id",
        "campaign_name", "route", "campaign_pid", "client_id", "user_id",
        "timestamp", "crqid", "request_id", "sender_uuid", "inmsid", "dlt_te_id",
        "event_name", "event", "failure_reason", "sms_length",
        "upper_case_event_name", "dry_run",
    ]
    list_display = ["id", "phone", "status", "request_id", "dry_run", "created_at"]
    list_filter = ["status", "dry_run"]
    search_fields = ["phone", "request_id", "campaign_name", "campaign_pid"]
    date_hierarchy = "created_at"
    list_per_page = 25

    def has_change_permission(self, request: HttpRequest, obj: SMSWebhook | None = None):
        return False

    def has_add_permission(self, request: HttpRequest):
        return False
