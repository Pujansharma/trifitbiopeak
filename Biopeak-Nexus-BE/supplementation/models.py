from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.db.models.functions import Lower

from accounts.utils import get_user_model
from core.utils.models import BaseUUIDModel
from supplementation.utils.constants import (
    AiRecommendationItemDecision,
    AiRecommendationItemOrigin,
    AiRecommendationStatus,
    AllergenName,
    AllergenPresenceType,
    ConstraintKind,
    DietaryAttribute,
    ProtocolAiJobStatus,
    ProtocolChangeType,
    ProtocolEventAction,
    ProtocolItemFrequency,
    ProtocolItemTiming,
    ProtocolVersionStatus,
    RawMaterialSourceType,
    SupplementForm,
)

User = get_user_model()


class Brand(BaseUUIDModel):
    name = models.CharField(max_length=200)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                Lower("name"),
                name="uniq_supplement_brand_name",
            ),
        ]
        indexes = [
            models.Index(fields=["name"], name="suppl_brand_name_idx"),
        ]

    def __str__(self):
        return f"{self.pk}"


class Supplement(BaseUUIDModel):
    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="supplements",
    )
    product_name = models.CharField(max_length=255)
    form = models.CharField(max_length=32, choices=SupplementForm)
    sku = models.CharField(max_length=64)
    manufacturer = models.CharField(max_length=255)
    raw_material_source_type = models.CharField(
        max_length=32,
        choices=RawMaterialSourceType,
    )
    pack_quantity_info = models.CharField(max_length=255)
    serving_size = models.CharField(max_length=128)
    serving_container = models.PositiveIntegerField()
    market_country_code = models.CharField(max_length=2)
    product_url = models.URLField(blank=True, default="")
    dietary_attributes = ArrayField(
        base_field=models.CharField(max_length=32, choices=DietaryAttribute),
        default=list,
        blank=True,
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplements",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("sku"),
                name="uniq_supplement_sku",
            ),
            models.UniqueConstraint(
                Lower("product_name"),
                "brand",
                name="uniq_supplement_brand_product_name",
            ),
        ]
        indexes = [
            models.Index(fields=["form"], name="suppl_form_idx"),
            models.Index(fields=["product_name"], name="suppl_product_name_idx"),
            models.Index(
                fields=["brand", "product_name"],
                name="suppl_brand_product_idx",
            ),
            models.Index(fields=["sku"], name="suppl_sku_idx"),
            GinIndex(
                fields=["dietary_attributes"],
                name="suppl_dietary_attrs_gin",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class SupplementActiveIngredient(BaseUUIDModel):
    supplement = models.ForeignKey(
        Supplement,
        on_delete=models.CASCADE,
        related_name="active_ingredients",
    )
    ingredient_name = models.CharField(max_length=255)
    serving = models.DecimalField(max_digits=12, decimal_places=4)
    unit = models.CharField(max_length=32)
    form = models.CharField(max_length=128, blank=True, default="")
    source = models.CharField(max_length=255, blank=True, default="")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "created_at"]
        indexes = [
            models.Index(
                fields=["supplement", "position"],
                name="suppl_ingredient_pos_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class SupplementAllergen(BaseUUIDModel):
    supplement = models.ForeignKey(
        Supplement,
        on_delete=models.CASCADE,
        related_name="allergens",
    )
    name = models.CharField(max_length=32, choices=AllergenName)
    presence_type = models.CharField(max_length=32, choices=AllergenPresenceType)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplement", "name"],
                name="uniq_supplement_allergen_name",
            ),
        ]
        indexes = [
            models.Index(
                fields=["supplement", "name"],
                name="suppl_allergen_name_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ClientConstraint(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="supplement_constraints",
    )
    kind = models.CharField(max_length=32, choices=ConstraintKind)
    name = models.CharField(max_length=255)
    severity = models.CharField(max_length=64, null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplement_constraints",
    )

    class Meta:
        ordering = ["name", "created_at"]
        indexes = [
            models.Index(
                fields=["customer_profile", "is_active"],
                name="suppl_constraint_prof_idx",
            ),
            models.Index(
                fields=["customer_profile", "kind"],
                name="suppl_constraint_kind_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class Protocol(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="supplement_protocols",
    )
    name = models.CharField(max_length=255)
    purpose = models.TextField()
    current_version = models.ForeignKey(
        "ProtocolVersion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_supplement_protocols",
    )

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["customer_profile"],
                name="suppl_protocol_prof_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ProtocolVersion(BaseUUIDModel):
    protocol = models.ForeignKey(
        Protocol,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(max_length=32, choices=ProtocolVersionStatus)
    notes = models.TextField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    review_on = models.DateField(null=True, blank=True)
    is_ongoing = models.BooleanField(default=False)
    summary_notes = models.TextField(null=True, blank=True)
    supersedes = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="successors",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_protocol_versions",
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="published_protocol_versions",
    )
    approval_notes = models.TextField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_protocol_versions",
    )
    cancellation_reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["protocol", "version_number"],
                name="uniq_protocol_version_no",
            ),
            models.UniqueConstraint(
                fields=["protocol"],
                condition=models.Q(status=ProtocolVersionStatus.ACTIVE),
                name="uniq_protocol_one_active",
            ),
        ]
        indexes = [
            models.Index(
                fields=["protocol", "status"],
                name="suppl_ver_protocol_stat_idx",
            ),
            models.Index(
                fields=["status", "starts_on", "ends_on"],
                name="suppl_ver_window_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ProtocolItem(BaseUUIDModel):
    version = models.ForeignKey(
        ProtocolVersion,
        on_delete=models.CASCADE,
        related_name="items",
    )
    supplement = models.ForeignKey(
        Supplement,
        on_delete=models.PROTECT,
        related_name="protocol_items",
    )
    dosage = models.TextField()
    frequency = models.CharField(max_length=32)
    custom_frequency = models.TextField(null=True, blank=True)
    timing = models.CharField(max_length=32)
    duration = models.TextField()
    instructions = models.TextField()
    rationale = models.TextField()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(frequency__in=ProtocolItemFrequency.values),
                name="protocol_item_frequency_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(timing__in=ProtocolItemTiming.values),
                name="protocol_item_timing_valid",
            ),
            models.UniqueConstraint(
                fields=["version", "supplement"],
                name="uniq_protocol_item_version_supplement",
            ),
        ]
        indexes = [
            models.Index(
                fields=["version", "created_at"],
                name="suppl_item_version_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ProtocolEvent(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="supplement_events",
    )
    protocol = models.ForeignKey(
        Protocol,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    protocol_version = models.ForeignKey(
        ProtocolVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="events",
    )
    actor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="supplement_protocol_events",
    )
    action = models.CharField(max_length=32, choices=ProtocolEventAction)
    reason = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    client_visible = models.BooleanField(default=False)
    client_title = models.TextField(null=True, blank=True)
    client_reason = models.TextField(null=True, blank=True)
    change_type = models.CharField(
        max_length=32,
        choices=ProtocolChangeType,
        null=True,
        blank=True,
    )
    effective_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["customer_profile", "created_at"],
                name="suppl_event_prof_created_idx",
            ),
            models.Index(
                fields=["customer_profile", "action"],
                name="suppl_event_prof_action_idx",
            ),
            models.Index(
                fields=["protocol", "created_at"],
                name="suppl_event_proto_created_idx",
            ),
            models.Index(
                fields=["protocol_version", "created_at"],
                name="suppl_event_ver_created_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class ProtocolAiJob(BaseUUIDModel):
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="protocol_ai_jobs",
    )
    requested_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="queued_protocol_ai_jobs",
    )
    name = models.CharField(max_length=255)
    purpose = models.TextField()
    notes = models.TextField(blank=True, default="")
    supplement_ids = ArrayField(base_field=models.UUIDField())
    status = models.CharField(
        max_length=32,
        default=ProtocolAiJobStatus.PENDING,
    )
    attempt_count = models.PositiveSmallIntegerField(default=0)
    error_detail = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=ProtocolAiJobStatus.values),
                name="ai_job_status_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "created_at"],
                name="suppl_ai_job_status_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class AiRecommendation(BaseUUIDModel):
    job = models.OneToOneField(
        ProtocolAiJob,
        on_delete=models.PROTECT,
        related_name="recommendation",
    )
    customer_profile = models.ForeignKey(
        "customers.CustomerProfile",
        on_delete=models.PROTECT,
        related_name="ai_recommendations",
    )
    name = models.CharField(max_length=255)
    purpose = models.TextField()
    notes = models.TextField(blank=True, default="")
    model = models.CharField(max_length=128)
    status = models.CharField(
        max_length=32,
        default=AiRecommendationStatus.UNDER_REVIEW,
    )
    protocol_version = models.ForeignKey(
        ProtocolVersion,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_recommendations",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=AiRecommendationStatus.values),
                name="ai_rec_status_valid",
            ),
            models.UniqueConstraint(
                fields=["protocol_version"],
                condition=models.Q(protocol_version__isnull=False),
                name="uniq_ai_rec_protocol_version",
            ),
        ]
        indexes = [
            models.Index(
                fields=["customer_profile", "created_at"],
                name="suppl_ai_rec_profile_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"


class AiRecommendationItem(BaseUUIDModel):
    recommendation = models.ForeignKey(
        AiRecommendation,
        on_delete=models.CASCADE,
        related_name="items",
    )
    supplement = models.ForeignKey(
        Supplement,
        on_delete=models.PROTECT,
        related_name="ai_recommendation_items",
    )
    origin = models.CharField(max_length=32)
    decision = models.CharField(
        max_length=32,
        default=AiRecommendationItemDecision.PENDING,
    )
    dosage = models.TextField()
    frequency = models.CharField(max_length=32)
    custom_frequency = models.TextField(null=True, blank=True)
    timing = models.CharField(max_length=32)
    duration = models.TextField()
    instructions = models.TextField()
    rationale = models.TextField()
    final_dosage = models.TextField(null=True, blank=True)
    final_frequency = models.CharField(max_length=32, null=True, blank=True)
    final_custom_frequency = models.TextField(null=True, blank=True)
    final_timing = models.CharField(max_length=32, null=True, blank=True)
    final_duration = models.TextField(null=True, blank=True)
    final_instructions = models.TextField(null=True, blank=True)
    final_rationale = models.TextField(null=True, blank=True)
    reason = models.TextField(null=True, blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recommendation", "supplement"],
                name="uniq_ai_item_supplement",
            ),
            models.CheckConstraint(
                condition=models.Q(origin__in=AiRecommendationItemOrigin.values),
                name="ai_item_origin_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(decision__in=AiRecommendationItemDecision.values),
                name="ai_item_decision_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(frequency__in=ProtocolItemFrequency.values),
                name="ai_item_frequency_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(timing__in=ProtocolItemTiming.values),
                name="ai_item_timing_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(final_frequency__isnull=True)
                | models.Q(final_frequency__in=ProtocolItemFrequency.values),
                name="ai_item_final_freq_valid",
            ),
            models.CheckConstraint(
                condition=models.Q(final_timing__isnull=True)
                | models.Q(final_timing__in=ProtocolItemTiming.values),
                name="ai_item_final_time_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["recommendation", "created_at"],
                name="suppl_ai_item_rec_idx",
            ),
        ]

    def __str__(self):
        return f"{self.pk}"
