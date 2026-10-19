# Generated from wearables/models.py for Biopeak Phase 1.
# Run python manage.py makemigrations --check --dry-run after installing dependencies.
import uuid
from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import migrations, models
from django.utils.translation import gettext_lazy as _
# Frozen migration snapshot: never import live application TextChoices or
# algorithm defaults. Future changes to runtime enums must not change the
# meaning of an already-applied database migration.
FROZEN_WEARABLESOURCE_CHOICES = [('Apple Health', 'Apple Health'), ('Health Connect', 'Health Connect'), ('Samsung Health', 'Samsung Health'), ('Garmin', 'Garmin'), ('Fitbit', 'Fitbit'), ('Oura', 'Oura'), ('Polar', 'Polar'), ('Withings', 'Withings'), ('Whoop', 'Whoop'), ('Dexcom', 'Dexcom'), ('Strava', 'Strava')]
FROZEN_CONNECTIONMETHOD_CHOICES = [('api', 'API authorization'), ('sdk', 'Native SDK')]
FROZEN_CONNECTIONSTATUS_CHOICES = [('never_connected', 'Never connected'), ('connecting', 'Connecting'), ('authorizing', 'Authorizing'), ('permission_denied', 'Permission denied'), ('connected_importing', 'Connected — importing'), ('connected_active', 'Connected — active'), ('connected_partial', 'Connected — partial'), ('connected_idle', 'Connected — idle'), ('authorization_expired', 'Authorization expired'), ('disconnected', 'Disconnected'), ('reconnected', 'Reconnected'), ('historical_reimport', 'Historical re-import'), ('provider_error', 'Provider error')]
FROZEN_AUTHORIZATIONSTATUS_CHOICES = [('not_started', 'Not started'), ('pending', 'Pending'), ('authorized', 'Authorized'), ('denied', 'Denied'), ('expired', 'Expired'), ('revoked', 'Revoked'), ('error', 'Error')]
FROZEN_PERMISSIONSTATUS_CHOICES = [('unknown', 'Unknown'), ('not_determined', 'Not determined'), ('granted', 'Granted'), ('limited', 'Limited'), ('denied', 'Denied')]
FROZEN_HISTORICALIMPORTSTATUS_CHOICES = [('not_started', 'Not started'), ('running', 'Running'), ('partial', 'Partial'), ('completed', 'Completed'), ('failed', 'Failed')]
FROZEN_HEALTHDOMAIN_CHOICES = [('sleep', 'Sleep'), ('activity', 'Activity'), ('heart', 'Heart'), ('recovery', 'Recovery'), ('body', 'Body'), ('workouts', 'Workouts')]
FROZEN_CONFIDENCELEVEL_CHOICES = [('high', 'High'), ('medium', 'Medium'), ('low', 'Low'), ('unknown', 'Unknown')]
FROZEN_DOCUMENTSTATUS_CHOICES = [('received', 'Received'), ('queued', 'Queued'), ('processed', 'Processed'), ('duplicate', 'Duplicate'), ('rejected', 'Rejected'), ('failed', 'Failed')]
FROZEN_HEALTHJOBTYPE_CHOICES = [('normalize_document', 'Normalize document'), ('refresh_analytics', 'Refresh analytics'), ('refresh_connection', 'Refresh connection'), ('revoke_connection', 'Revoke connection'), ('recovery_pull', 'ROOK recovery pull'), ('freshness_check', 'Freshness check'), ('remap_timezone', 'Remap member local dates')]
FROZEN_HEALTHJOBSTATUS_CHOICES = [('pending', 'Pending'), ('running', 'Running'), ('completed', 'Completed'), ('failed', 'Failed')]
FROZEN_CONSENTSTATUS_CHOICES = [('granted', 'Granted'), ('revoked', 'Revoked')]
FROZEN_PREFERREDUNITS_CHOICES = [('metric', 'Metric'), ('imperial', 'Imperial')]



class Migration(migrations.Migration):
    initial = True
    dependencies = [
        ("customers", "0020_customerprofilefeature_wearables_feature_choice"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="RookMemberIdentity",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.OneToOneField(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="rook_identity",
                )),
            ("rook_user_id", models.CharField(max_length=50, unique=True)),
            ("timezone_name", models.CharField(max_length=64, default='Asia/Kolkata')),
            ("preferred_units", models.CharField(
                    max_length=16,
                    choices=FROZEN_PREFERREDUNITS_CHOICES,
                    default='metric',
                )),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="WearableConsent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="wearable_consents",
                )),
            ("granted_by", models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    null=True,
                    blank=True,
                    on_delete=models.SET_NULL,
                    related_name="wearable_consents_granted",
                )),
            ("status", models.CharField(
                    max_length=16,
                    choices=FROZEN_CONSENTSTATUS_CHOICES,
                    default='granted',
                )),
            ("version", models.CharField(max_length=32)),
            ("purpose", models.CharField(
                    max_length=255,
                    default="Wearable ingestion and longitudinal health storage",
                )),
            ("granted_at", models.DateTimeField()),
            ("revoked_at", models.DateTimeField(null=True, blank=True)),
            ("ip_address", models.GenericIPAddressField(null=True, blank=True)),
            ("user_agent", models.CharField(max_length=512, blank=True)),
            ],
            options={"ordering": ["-granted_at"]},
        ),
        migrations.CreateModel(
            name="WearableConnection",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="wearable_connections",
                )),
            ("identity", models.ForeignKey(
                    "wearables.rookmemberidentity",
                    on_delete=models.CASCADE,
                    related_name="connections",
                )),
            ("data_source", models.CharField(max_length=32, choices=FROZEN_WEARABLESOURCE_CHOICES)),
            ("connection_method", models.CharField(max_length=8, choices=FROZEN_CONNECTIONMETHOD_CHOICES)),
            ("status", models.CharField(
                    max_length=32,
                    choices=FROZEN_CONNECTIONSTATUS_CHOICES,
                    default='never_connected',
                )),
            ("authorization_status", models.CharField(
                    max_length=24,
                    choices=FROZEN_AUTHORIZATIONSTATUS_CHOICES,
                    default='not_started',
                )),
            ("permission_status", models.CharField(
                    max_length=24,
                    choices=FROZEN_PERMISSIONSTATUS_CHOICES,
                    default='unknown',
                )),
            ("import_status", models.CharField(
                    max_length=24,
                    choices=FROZEN_HISTORICALIMPORTSTATUS_CHOICES,
                    default='not_started',
                )),
            ("capabilities", models.JSONField(default=list, blank=True)),
            ("historical_days_requested", models.PositiveSmallIntegerField(default=29)),
            ("connected_at", models.DateTimeField(null=True, blank=True)),
            ("disconnected_at", models.DateTimeField(null=True, blank=True)),
            ("last_successful_sync", models.DateTimeField(null=True, blank=True)),
            ("last_webhook_received_at", models.DateTimeField(null=True, blank=True)),
            ("import_started_at", models.DateTimeField(null=True, blank=True)),
            ("import_completed_at", models.DateTimeField(null=True, blank=True)),
            ("available_from", models.DateTimeField(null=True, blank=True)),
            ("available_to", models.DateTimeField(null=True, blank=True)),
            ("last_error_code", models.CharField(max_length=64, blank=True)),
            ("last_error_detail", models.CharField(max_length=512, blank=True)),
            ],
            options={"ordering": ["data_source"]},
        ),
        migrations.CreateModel(
            name="WearableConnectionEvent",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("connection", models.ForeignKey(
                    "wearables.wearableconnection",
                    on_delete=models.CASCADE,
                    related_name="events",
                )),
            ("event_type", models.CharField(max_length=64)),
            ("previous_status", models.CharField(max_length=32, blank=True)),
            ("current_status", models.CharField(max_length=32)),
            ("actor_user", models.ForeignKey(
                    settings.AUTH_USER_MODEL,
                    null=True,
                    blank=True,
                    on_delete=models.SET_NULL,
                    related_name="wearable_connection_events",
                )),
            ("correlation_id", models.CharField(max_length=128, blank=True, db_index=True)),
            ("detail", models.CharField(max_length=512, blank=True)),
            ("payload", models.JSONField(default=dict, blank=True)),
            ],
            options={"ordering": ["-created_at"]},
        ),
        migrations.CreateModel(
            name="RookHealthDocument",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="rook_health_documents",
                )),
            ("identity", models.ForeignKey(
                    "wearables.rookmemberidentity",
                    on_delete=models.CASCADE,
                    related_name="health_documents",
                )),
            ("document_identity", models.CharField(max_length=64, unique=True)),
            ("content_hash", models.CharField(max_length=64)),
            ("data_structure", models.CharField(max_length=128, db_index=True)),
            ("document_version", models.PositiveIntegerField(default=1)),
            ("observed_at", models.DateTimeField(db_index=True)),
            ("source_key", models.CharField(max_length=64, blank=True, db_index=True)),
            ("data_sources", models.JSONField(default=list, blank=True)),
            ("source_label", models.CharField(max_length=255, blank=True)),
            ("device_metadata", models.JSONField(default=list, blank=True)),
            ("source_contexts", models.JSONField(default=list, blank=True)),
            ("payload", models.JSONField(default=dict)),
            ("status", models.CharField(
                    max_length=16,
                    choices=FROZEN_DOCUMENTSTATUS_CHOICES,
                    default='received',
                )),
            ("received_at", models.DateTimeField()),
            ("processed_at", models.DateTimeField(null=True, blank=True)),
            ("failure_detail", models.CharField(max_length=512, blank=True)),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.CreateModel(
            name="RookWebhookReceipt",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("receipt_key", models.CharField(max_length=64, unique=True)),
            ("rook_user_id", models.CharField(max_length=50, blank=True, db_index=True)),
            ("document", models.ForeignKey(
                    "wearables.rookhealthdocument",
                    null=True,
                    blank=True,
                    on_delete=models.SET_NULL,
                    related_name="receipts",
                )),
            ("signature_valid", models.BooleanField(default=False)),
            ("status", models.CharField(
                    max_length=16,
                    choices=FROZEN_DOCUMENTSTATUS_CHOICES,
                    default='received',
                )),
            ("reason", models.CharField(max_length=128, blank=True)),
            ("payload", models.JSONField(default=dict, blank=True)),
            ("received_at", models.DateTimeField()),
            ],
            options={"ordering": ["-received_at"]},
        ),
        migrations.CreateModel(
            name="HealthObservation",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="health_observations",
                )),
            ("document", models.ForeignKey(
                    "wearables.rookhealthdocument",
                    on_delete=models.CASCADE,
                    related_name="observations",
                )),
            ("connection", models.ForeignKey(
                    "wearables.wearableconnection",
                    null=True,
                    blank=True,
                    on_delete=models.SET_NULL,
                    related_name="observations",
                )),
            ("observation_identity", models.CharField(max_length=64, unique=True)),
            ("domain", models.CharField(max_length=16, choices=FROZEN_HEALTHDOMAIN_CHOICES, db_index=True)),
            ("metric", models.CharField(max_length=128, db_index=True)),
            ("field_path", models.CharField(max_length=512)),
            ("observed_at", models.DateTimeField(db_index=True)),
            ("local_date", models.DateField(db_index=True)),
            ("numeric_value", models.FloatField(null=True, blank=True)),
            ("text_value", models.CharField(max_length=512, blank=True)),
            ("boolean_value", models.BooleanField(null=True, blank=True)),
            ("unit", models.CharField(max_length=32, blank=True)),
            ("source_key", models.CharField(max_length=64, blank=True, db_index=True)),
            ("data_sources", models.JSONField(default=list, blank=True)),
            ("provenance", models.JSONField(default=dict, blank=True)),
            ("confidence", models.FloatField(default=1.0)),
            ("document_version", models.PositiveIntegerField(default=1)),
            ("is_current", models.BooleanField(default=True, db_index=True)),
            ],
            options={"ordering": ["-observed_at"]},
        ),
        migrations.CreateModel(
            name="HealthDailySummary",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="health_daily_summaries",
                )),
            ("domain", models.CharField(max_length=16, choices=FROZEN_HEALTHDOMAIN_CHOICES)),
            ("metric", models.CharField(max_length=128)),
            ("local_date", models.DateField()),
            ("source_key", models.CharField(max_length=64, blank=True)),
            ("count", models.PositiveIntegerField(default=0)),
            ("minimum", models.FloatField(null=True, blank=True)),
            ("maximum", models.FloatField(null=True, blank=True)),
            ("average", models.FloatField(null=True, blank=True)),
            ("total", models.FloatField(null=True, blank=True)),
            ("latest", models.FloatField(null=True, blank=True)),
            ("unit", models.CharField(max_length=32, blank=True)),
            ("completeness", models.FloatField(default=0.0)),
            ("first_observed_at", models.DateTimeField(null=True, blank=True)),
            ("last_observed_at", models.DateTimeField(null=True, blank=True)),
            ],
            options={"ordering": ["-local_date"]},
        ),
        migrations.CreateModel(
            name="HealthDomainSnapshot",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    on_delete=models.CASCADE,
                    related_name="health_domain_snapshots",
                )),
            ("domain", models.CharField(max_length=16, choices=FROZEN_HEALTHDOMAIN_CHOICES)),
            ("state", models.CharField(max_length=32)),
            ("card", models.JSONField(default=dict, encoder=DjangoJSONEncoder)),
            ("algorithm_version", models.CharField(max_length=32, default='wearables-v1.2')),
            ("confidence", models.CharField(
                    max_length=16,
                    choices=FROZEN_CONFIDENCELEVEL_CHOICES,
                    default='unknown',
                )),
            ("generated_at", models.DateTimeField()),
            ],
            options={"ordering": ["domain"]},
        ),
        migrations.CreateModel(
            name="HealthProcessingJob",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid7, primary_key=True, db_index=True, editable=False)),
            ("is_active", models.BooleanField(_("active status"), default=True, help_text=_("Designates whether this is marked as active"))),
            ("created_at", models.DateTimeField(_("created at"), auto_now_add=True, help_text=_("Designates when this object was created."))),
            ("updated_at", models.DateTimeField(_("updated at"), auto_now=True, help_text=_("Designates when this object was last updated."))),
            ("customer_profile", models.ForeignKey(
                    "customers.customerprofile",
                    null=True,
                    blank=True,
                    on_delete=models.CASCADE,
                    related_name="health_processing_jobs",
                )),
            ("document", models.ForeignKey(
                    "wearables.rookhealthdocument",
                    null=True,
                    blank=True,
                    on_delete=models.CASCADE,
                    related_name="processing_jobs",
                )),
            ("connection", models.ForeignKey(
                    "wearables.wearableconnection",
                    null=True,
                    blank=True,
                    on_delete=models.CASCADE,
                    related_name="processing_jobs",
                )),
            ("job_type", models.CharField(max_length=32, choices=FROZEN_HEALTHJOBTYPE_CHOICES)),
            ("status", models.CharField(
                    max_length=16,
                    choices=FROZEN_HEALTHJOBSTATUS_CHOICES,
                    default='pending',
                )),
            ("idempotency_key", models.CharField(max_length=128, unique=True)),
            ("payload", models.JSONField(default=dict, blank=True)),
            ("attempt_count", models.PositiveIntegerField(default=0)),
            ("scheduled_at", models.DateTimeField()),
            ("started_at", models.DateTimeField(null=True, blank=True)),
            ("completed_at", models.DateTimeField(null=True, blank=True)),
            ("locked_at", models.DateTimeField(null=True, blank=True)),
            ("failure_detail", models.CharField(max_length=512, blank=True)),
            ],
            options={"ordering": ["scheduled_at"]},
        ),
        migrations.AddIndex(model_name="wearableconsent", index=models.Index(fields=["customer_profile", "status", "granted_at"], name="w_wearablecons_1_idx")),
        migrations.AddConstraint(model_name="wearableconnection", constraint=models.UniqueConstraint(
                fields=["customer_profile", "data_source"],
                name="uniq_profile_wearable_source",
            )),
        migrations.AddIndex(model_name="wearableconnection", index=models.Index(fields=["customer_profile", "status"], name="w_wearableconn_1_idx")),
        migrations.AddIndex(model_name="wearableconnection", index=models.Index(fields=["identity", "data_source"], name="w_wearableconn_2_idx")),
        migrations.AddIndex(model_name="wearableconnectionevent", index=models.Index(fields=["connection", "created_at"], name="w_conn_event_1_idx")),
        migrations.AddIndex(model_name="rookhealthdocument", index=models.Index(fields=["customer_profile", "observed_at"], name="w_rookhealthdo_1_idx")),
        migrations.AddIndex(model_name="rookhealthdocument", index=models.Index(
                fields=["customer_profile", "data_structure", "observed_at"],
                name="wear_doc_prof_struct_time",
            )),
        migrations.AddIndex(model_name="rookhealthdocument", index=models.Index(fields=["status", "received_at"], name="w_rookhealthdo_3_idx")),
        migrations.AddIndex(model_name="rookwebhookreceipt", index=models.Index(fields=["status", "received_at"], name="w_rookwebhookr_1_idx")),
        migrations.AddIndex(model_name="healthobservation", index=models.Index(
                fields=["customer_profile", "domain", "observed_at"],
                name="wear_obs_prof_domain_time",
            )),
        migrations.AddIndex(model_name="healthobservation", index=models.Index(
                fields=["customer_profile", "metric", "local_date"],
                name="wear_obs_prof_metric_day",
            )),
        migrations.AddConstraint(model_name="healthdailysummary", constraint=models.UniqueConstraint(
                fields=[
                    "customer_profile",
                    "domain",
                    "metric",
                    "local_date",
                    "source_key",
                ],
                name="uniq_health_daily_metric_source",
            )),
        migrations.AddIndex(model_name="healthdailysummary", index=models.Index(
                fields=["customer_profile", "domain", "local_date"],
                name="wear_daily_prof_domain_day",
            )),
        migrations.AddConstraint(model_name="healthdomainsnapshot", constraint=models.UniqueConstraint(
                fields=["customer_profile", "domain"],
                name="uniq_profile_health_domain_snapshot",
            )),
        migrations.AddIndex(model_name="healthprocessingjob", index=models.Index(fields=["status", "scheduled_at"], name="w_healthproces_1_idx")),
    ]
