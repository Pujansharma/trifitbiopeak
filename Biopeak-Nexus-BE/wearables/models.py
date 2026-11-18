# ruff: noqa: RUF012

import uuid

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models

from accounts.customers.models import CustomerProfile
from core.utils.models import BaseUUIDModel
from wearables.utils.constants import (
    ALGORITHM_VERSION,
    AuthorizationStatus,
    ConfidenceLevel,
    ConnectionMethod,
    ConnectionStatus,
    ConsentStatus,
    DocumentStatus,
    HealthDomain,
    HealthJobStatus,
    HealthJobType,
    HistoricalImportStatus,
    PermissionStatus,
    PreferredUnits,
    WearableSource,
)


class RookMemberIdentity(BaseUUIDModel):
    customer_profile = models.OneToOneField(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="rook_identity",
    )
    rook_user_id = models.CharField(max_length=50, unique=True)
    timezone_name = models.CharField(max_length=64, default=settings.TIME_ZONE)
    preferred_units = models.CharField(
        max_length=16,
        choices=PreferredUnits,
        default=PreferredUnits.METRIC,
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.rook_user_id


class WearableConsent(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="wearable_consents",
    )
    granted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wearable_consents_granted",
    )
    status = models.CharField(
        max_length=16,
        choices=ConsentStatus,
        default=ConsentStatus.GRANTED,
    )
    version = models.CharField(max_length=32)
    purpose = models.CharField(
        max_length=255,
        default="Wearable ingestion and longitudinal health storage",
    )
    granted_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["-granted_at"]
        indexes = [
            models.Index(fields=["customer_profile", "status", "granted_at"], name="w_wearablecons_1_idx"),
        ]

    def __str__(self):
        return f"{self.customer_profile_id}:{self.version}:{self.status}"


class WearableConnection(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="wearable_connections",
    )
    identity = models.ForeignKey(
        RookMemberIdentity,
        on_delete=models.CASCADE,
        related_name="connections",
    )
    data_source = models.CharField(max_length=32, choices=WearableSource)
    connection_method = models.CharField(max_length=8, choices=ConnectionMethod)
    status = models.CharField(
        max_length=32,
        choices=ConnectionStatus,
        default=ConnectionStatus.NEVER_CONNECTED,
    )
    authorization_status = models.CharField(
        max_length=24,
        choices=AuthorizationStatus,
        default=AuthorizationStatus.NOT_STARTED,
    )
    permission_status = models.CharField(
        max_length=24,
        choices=PermissionStatus,
        default=PermissionStatus.UNKNOWN,
    )
    import_status = models.CharField(
        max_length=24,
        choices=HistoricalImportStatus,
        default=HistoricalImportStatus.NOT_STARTED,
    )
    capabilities = models.JSONField(default=list, blank=True)
    historical_days_requested = models.PositiveSmallIntegerField(default=29)
    connected_at = models.DateTimeField(null=True, blank=True)
    disconnected_at = models.DateTimeField(null=True, blank=True)
    # Request/coverage metadata must not be inferred from webhook receipt time.
    authorization_generation = models.UUIDField(default=uuid.uuid4, editable=False)
    last_sync_requested_at = models.DateTimeField(null=True, blank=True)
    # Manual admission is distinct from webhook freshness and completed pulls.
    last_manual_sync_queued_at = models.DateTimeField(null=True, blank=True)
    pending_sync_requested_at = models.DateTimeField(null=True, blank=True)
    last_data_processed_at = models.DateTimeField(null=True, blank=True)
    last_pull_completed_at = models.DateTimeField(null=True, blank=True)
    synced_through = models.DateTimeField(null=True, blank=True)
    last_successful_sync = models.DateTimeField(null=True, blank=True)
    last_webhook_received_at = models.DateTimeField(null=True, blank=True)
    import_started_at = models.DateTimeField(null=True, blank=True)
    import_completed_at = models.DateTimeField(null=True, blank=True)
    available_from = models.DateTimeField(null=True, blank=True)
    available_to = models.DateTimeField(null=True, blank=True)
    last_error_code = models.CharField(max_length=64, blank=True)
    last_error_detail = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["data_source"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer_profile", "data_source"],
                name="uniq_profile_wearable_source",
            ),
        ]
        indexes = [
            models.Index(fields=["customer_profile", "status"], name="w_wearableconn_1_idx"),
            models.Index(fields=["identity", "data_source"], name="w_wearableconn_2_idx"),
        ]

    def __str__(self):
        return f"{self.customer_profile_id}:{self.data_source}"


class WearableConnectionEvent(BaseUUIDModel):
    connection = models.ForeignKey(
        WearableConnection,
        on_delete=models.CASCADE,
        related_name="events",
    )
    event_type = models.CharField(max_length=64)
    previous_status = models.CharField(max_length=32, blank=True)
    current_status = models.CharField(max_length=32)
    actor_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="wearable_connection_events",
    )
    correlation_id = models.CharField(max_length=128, blank=True, db_index=True)
    detail = models.CharField(max_length=512, blank=True)
    payload = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["connection", "created_at"], name="w_conn_event_1_idx")]

    def __str__(self):
        return f"{self.connection_id}:{self.event_type}"


class RookWebhookReceipt(BaseUUIDModel):
    """One accepted or rejected ROOK delivery.

    While QUEUED the raw ROOK body is held in ``payload``; it is replaced by a
    compact summary once the delivery is processed or rejected. ``document_identity``
    is the canonical correction key (member, structure, UTC instant), and
    ``document_version`` / ``content_hash`` decide duplicates and corrections.
    """

    receipt_key = models.CharField(max_length=64, unique=True)
    rook_user_id = models.CharField(max_length=50, blank=True, db_index=True)
    document_identity = models.CharField(max_length=64, blank=True)
    document_version = models.PositiveIntegerField(default=1)
    content_hash = models.CharField(max_length=64, blank=True)
    observed_at = models.DateTimeField(null=True, blank=True)
    signature_valid = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16,
        choices=DocumentStatus,
        default=DocumentStatus.RECEIVED,
    )
    reason = models.CharField(max_length=128, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    received_at = models.DateTimeField()

    class Meta:
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["status", "received_at"], name="w_rookwebhookr_1_idx"),
            models.Index(fields=["document_identity", "status"], name="w_rookwebhook_ident_idx"),
        ]

    def __str__(self):
        return self.receipt_key


class HealthDailySummary(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="health_daily_summaries",
    )
    domain = models.CharField(max_length=16, choices=HealthDomain)
    metric = models.CharField(max_length=128)
    local_date = models.DateField()
    source_key = models.CharField(max_length=64, blank=True)
    count = models.PositiveIntegerField(default=0)
    minimum = models.FloatField(null=True, blank=True)
    maximum = models.FloatField(null=True, blank=True)
    average = models.FloatField(null=True, blank=True)
    total = models.FloatField(null=True, blank=True)
    latest = models.FloatField(null=True, blank=True)
    unit = models.CharField(max_length=32, blank=True)
    completeness = models.FloatField(default=0.0)
    first_observed_at = models.DateTimeField(null=True, blank=True)
    last_observed_at = models.DateTimeField(null=True, blank=True)
    # One entry per canonical ROOK document; see wearables/services/daily_contributions.py.
    contributions = models.JSONField(default=dict, blank=True)
    data_sources = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-local_date"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "customer_profile",
                    "domain",
                    "metric",
                    "local_date",
                    "source_key",
                ],
                name="uniq_health_daily_metric_source",
            ),
        ]
        indexes = [
            models.Index(
                fields=["customer_profile", "domain", "local_date"],
                name="wear_daily_prof_domain_day",
            ),
        ]

    def __str__(self):
        return f"{self.customer_profile_id}:{self.metric}:{self.local_date}"


class HealthDomainSnapshot(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        CustomerProfile,
        on_delete=models.CASCADE,
        related_name="health_domain_snapshots",
    )
    domain = models.CharField(max_length=16, choices=HealthDomain)
    state = models.CharField(max_length=32)
    card = models.JSONField(default=dict, encoder=DjangoJSONEncoder)
    algorithm_version = models.CharField(max_length=32, default=ALGORITHM_VERSION)
    confidence = models.CharField(
        max_length=16,
        choices=ConfidenceLevel,
        default=ConfidenceLevel.UNKNOWN,
    )
    generated_at = models.DateTimeField()

    class Meta:
        ordering = ["domain"]
        constraints = [
            models.UniqueConstraint(
                fields=["customer_profile", "domain"],
                name="uniq_profile_health_domain_snapshot",
            ),
        ]

    def __str__(self):
        return f"{self.customer_profile_id}:{self.domain}"


class RookOutbox(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        CustomerProfile,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="rook_outboxes",
    )
    connection = models.ForeignKey(
        WearableConnection,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="rook_outboxes",
    )
    job_type = models.CharField(max_length=32, choices=HealthJobType)
    status = models.CharField(
        max_length=16,
        choices=HealthJobStatus,
        default=HealthJobStatus.PENDING,
    )
    idempotency_key = models.CharField(max_length=128, unique=True)
    payload = models.JSONField(default=dict, blank=True)
    # Durable SQS notification intent. The job remains authoritative if send fails.
    wake_version = models.PositiveIntegerField(default=1)
    wake_sent_version = models.PositiveIntegerField(default=0)
    wake_next_attempt_at = models.DateTimeField(null=True, blank=True)
    claim_token = models.UUIDField(null=True, blank=True, editable=False)
    attempt_count = models.PositiveIntegerField(default=0)
    scheduled_at = models.DateTimeField()
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    failure_detail = models.CharField(max_length=512, blank=True)

    class Meta:
        ordering = ["scheduled_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["connection"],
                condition=models.Q(job_type=HealthJobType.FETCH_ROOK_DATA, status=HealthJobStatus.RUNNING),
                name="uniq_rook_running_fetch",
            ),
        ]
        indexes = [
            models.Index(fields=["status", "scheduled_at"], name="w_healthproces_1_idx"),
            models.Index(
                fields=["customer_profile", "job_type", "scheduled_at"],
                name="w_hjob_profile_type_s_idx",
            ),
            models.Index(
                fields=["connection", "job_type", "created_at"],
                name="w_hjob_conn_type_c_idx",
            ),
        ]

    def __str__(self):
        return f"{self.job_type}:{self.status}:{self.idempotency_key}"


class RookRequestBudget(models.Model):
    """Account-wide HTTP admission; includes calls from web and all worker roles."""

    scope = models.CharField(max_length=64, primary_key=True)
    revision = models.PositiveBigIntegerField(default=0)
    next_request_at = models.DateTimeField(null=True, blank=True)
    blocked_until = models.DateTimeField(null=True, blank=True)
    budget_date = models.DateField(null=True, blank=True)
    requests_today = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)
