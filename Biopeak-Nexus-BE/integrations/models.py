from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower

from accounts.utils import get_user_model
from core.utils.models import BaseModel, BaseUUIDModel
from integrations.utils.constants import (
    APP_DOWNLOAD_USER_AGENT_MAX_LENGTH,
    AppDownloadEntry,
    AppDownloadPlatform,
    CommunicationEventType,
    GoogleCalendarOutboxStatus,
    ProtocolAiOutboxStatus,
    TERMINAL_APPOINTMENT_EVENT_TYPES,
    TERMINAL_GOOGLE_OUTBOX_BLOCKING_STATUSES,
    TERMINAL_WHATSAPP_OUTBOX_BLOCKING_STATUSES,
    WhatsAppOutboxStatus,
)

User = get_user_model()


class GoogleCalendarConnection(BaseModel):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="google_calendar_connection",
        primary_key=True,
        db_index=True,
    )
    google_email = models.EmailField(null=True, blank=True)
    google_access_token = models.TextField(null=True, blank=True)
    google_refresh_token = models.TextField(null=True, blank=True)
    google_access_token_expires_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    watch_channel_id = models.CharField(null=True, blank=True, db_index=True)
    watch_channel_token = models.CharField(null=True, blank=True)
    watch_resource_id = models.CharField(null=True, blank=True)
    watch_expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("google_email"),
                name="uniq_google_calendar_connection_email",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class GoogleCalendarOutbox(BaseUUIDModel):
    """Dedicated Google Calendar sync queue (appointments + personal blocks/leave)."""

    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        related_name="google_calendar_messages",
        null=True,
        blank=True,
    )
    associate_availability_block = models.ForeignKey(
        "appointments.AssociateAvailabilityBlock",
        on_delete=models.CASCADE,
        related_name="google_calendar_messages",
        null=True,
        blank=True,
    )
    associate_leave = models.ForeignKey(
        "appointments.AssociateLeave",
        on_delete=models.CASCADE,
        related_name="google_calendar_messages",
        null=True,
        blank=True,
    )
    availability_series_id = models.UUIDField(null=True, blank=True, db_index=True)
    event_type = models.CharField(max_length=64, choices=CommunicationEventType)
    status = models.CharField(
        max_length=32,
        choices=GoogleCalendarOutboxStatus,
        default=GoogleCalendarOutboxStatus.PENDING,
        db_index=True,
    )
    error_code = models.CharField(max_length=64, blank=True)
    error_detail = models.TextField(blank=True)
    provider_response = models.JSONField(null=True, blank=True)
    skip_reason = models.CharField(max_length=255, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["appointment", "event_type"]),
            models.Index(
                fields=["appointment", "status"],
                name="integration_gcal_appt_stat_idx",
            ),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "event_type"],
                condition=Q(
                    event_type__in=TERMINAL_APPOINTMENT_EVENT_TYPES,
                    status__in=TERMINAL_GOOGLE_OUTBOX_BLOCKING_STATUSES,
                ),
                name="uniq_gcal_outbox_appointment_terminal_event",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        appointment__isnull=False,
                        associate_availability_block__isnull=True,
                        associate_leave__isnull=True,
                        availability_series_id__isnull=True,
                    )
                    | Q(
                        appointment__isnull=True,
                        associate_availability_block__isnull=False,
                        associate_leave__isnull=True,
                        availability_series_id__isnull=True,
                    )
                    | Q(
                        appointment__isnull=True,
                        associate_availability_block__isnull=True,
                        associate_leave__isnull=False,
                        availability_series_id__isnull=True,
                    )
                    | Q(
                        appointment__isnull=True,
                        associate_availability_block__isnull=True,
                        associate_leave__isnull=True,
                        availability_series_id__isnull=False,
                    )
                ),
                name="gcal_outbox_exactly_one_target",
            ),
            models.UniqueConstraint(
                fields=["availability_series_id"],
                condition=Q(
                    availability_series_id__isnull=False,
                    status__in=[
                        GoogleCalendarOutboxStatus.PENDING,
                        GoogleCalendarOutboxStatus.QUEUED,
                        GoogleCalendarOutboxStatus.FAILED,
                    ],
                ),
                name="uniq_gcal_outbox_series_open",
            ),
            models.UniqueConstraint(
                fields=["associate_availability_block"],
                condition=Q(
                    associate_availability_block__isnull=False,
                    status__in=[
                        GoogleCalendarOutboxStatus.PENDING,
                        GoogleCalendarOutboxStatus.QUEUED,
                        GoogleCalendarOutboxStatus.FAILED,
                    ],
                ),
                name="uniq_gcal_outbox_block_open",
            ),
            models.UniqueConstraint(
                fields=["associate_leave"],
                condition=Q(
                    associate_leave__isnull=False,
                    status__in=[
                        GoogleCalendarOutboxStatus.PENDING,
                        GoogleCalendarOutboxStatus.QUEUED,
                        GoogleCalendarOutboxStatus.FAILED,
                    ],
                ),
                name="uniq_gcal_outbox_leave_open",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ProtocolAiOutbox(BaseUUIDModel):
    """Dedicated SQS dispatch queue for ProtocolAiJob Luma calls."""

    job = models.OneToOneField(
        "supplementation.ProtocolAiJob",
        on_delete=models.CASCADE,
        related_name="outbox",
    )
    status = models.CharField(
        max_length=32,
        choices=ProtocolAiOutboxStatus,
        default=ProtocolAiOutboxStatus.PENDING,
        db_index=True,
    )
    error_detail = models.TextField(blank=True, default="")
    skip_reason = models.CharField(max_length=255, blank=True, default="")
    accepted_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ProtocolAiOutboxStatus.values),
                name="ai_outbox_status_valid",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class WhatsAppOutbox(BaseUUIDModel):
    """Dedicated WhatsApp send queue (appointments only)."""

    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        related_name="whatsapp_messages",
    )
    event_type = models.CharField(max_length=64, choices=CommunicationEventType)
    to_phone = models.CharField(max_length=32, blank=True)
    template_name = models.CharField(max_length=128, blank=True)
    template_language = models.CharField(max_length=16, blank=True)
    template_parameters = models.JSONField(default=list, blank=True)
    status = models.CharField(
        max_length=32,
        choices=WhatsAppOutboxStatus,
        default=WhatsAppOutboxStatus.PENDING,
        db_index=True,
    )
    wamid = models.CharField(max_length=255, blank=True, db_index=True)
    error_code = models.CharField(max_length=64, blank=True)
    error_detail = models.TextField(blank=True)
    provider_response = models.JSONField(null=True, blank=True)
    skip_reason = models.CharField(max_length=255, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    failed_at = models.DateTimeField(null=True, blank=True)
    attempt_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["status", "created_at"]),
            models.Index(fields=["appointment", "event_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["appointment", "event_type"],
                condition=Q(
                    event_type__in=TERMINAL_APPOINTMENT_EVENT_TYPES,
                    status__in=TERMINAL_WHATSAPP_OUTBOX_BLOCKING_STATUSES,
                ),
                name="uniq_whatsapp_outbox_appointment_terminal_event",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class CommunicationWebhookEvent(BaseUUIDModel):
    """Idempotency log for Meta WhatsApp status / inbound webhooks."""

    event_key = models.CharField(max_length=255, unique=True)
    wamid = models.CharField(max_length=255, blank=True, db_index=True)
    status = models.CharField(max_length=32, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.pk}"


class AppDownloadClick(BaseUUIDModel):
    """Append-only QR / deep-link hit for app store redirect."""

    platform = models.CharField(max_length=16, choices=AppDownloadPlatform, db_index=True)
    entry = models.CharField(
        max_length=32,
        choices=AppDownloadEntry,
        default=AppDownloadEntry.UA,
        db_index=True,
    )
    destination_url = models.URLField(max_length=512, blank=True)
    user_agent = models.CharField(max_length=APP_DOWNLOAD_USER_AGENT_MAX_LENGTH, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    source = models.CharField(max_length=128, blank=True, db_index=True)
    campaign = models.CharField(max_length=128, blank=True, db_index=True)
    referer = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["platform", "created_at"]),
            models.Index(fields=["entry", "created_at"]),
            models.Index(fields=["source", "created_at"]),
        ]

    def __str__(self):
        return f"{self.pk}"
