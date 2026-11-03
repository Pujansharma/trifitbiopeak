from django.contrib import admin

from supplementation.models import (
    AiRecommendation,
    AiRecommendationItem,
    Brand,
    ClientConstraint,
    Protocol,
    ProtocolAiJob,
    ProtocolEvent,
    ProtocolItem,
    ProtocolVersion,
    Supplement,
    SupplementActiveIngredient,
    SupplementAllergen,
)


class SupplementActiveIngredientInline(admin.TabularInline):
    model = SupplementActiveIngredient
    extra = 0


class SupplementAllergenInline(admin.TabularInline):
    model = SupplementAllergen
    extra = 0


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "is_active", "created_at"]
    search_fields = ["name"]
    list_filter = ["is_active"]


@admin.register(Supplement)
class SupplementAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "product_name",
        "brand",
        "form",
        "sku",
        "is_active",
        "created_at",
    ]
    search_fields = ["product_name", "sku", "brand__name", "manufacturer"]
    list_filter = ["form", "raw_material_source_type", "is_active"]
    raw_id_fields = ["brand", "created_by"]
    inlines = [SupplementActiveIngredientInline, SupplementAllergenInline]


@admin.register(ClientConstraint)
class ClientConstraintAdmin(admin.ModelAdmin):
    list_display = ["id", "customer_profile", "kind", "name", "is_active"]
    list_filter = ["kind", "is_active"]
    search_fields = ["name"]
    raw_id_fields = ["customer_profile", "created_by"]


@admin.register(Protocol)
class ProtocolAdmin(admin.ModelAdmin):
    list_display = ["id", "name", "customer_profile", "current_version", "is_active"]
    search_fields = ["name"]
    raw_id_fields = ["customer_profile", "current_version", "created_by"]


@admin.register(ProtocolVersion)
class ProtocolVersionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "protocol",
        "version_number",
        "status",
        "starts_on",
        "ends_on",
    ]
    list_filter = ["status", "is_active"]
    raw_id_fields = [
        "protocol",
        "supersedes",
        "approved_by",
        "published_by",
        "cancelled_by",
    ]


@admin.register(ProtocolEvent)
class ProtocolEventAdmin(admin.ModelAdmin):
    list_display = ["id", "customer_profile", "action", "client_visible", "created_at"]
    list_filter = ["action", "change_type", "client_visible"]
    raw_id_fields = ["customer_profile", "protocol", "protocol_version", "actor"]


@admin.register(ProtocolItem)
class ProtocolItemAdmin(admin.ModelAdmin):
    list_display = ["id", "version", "supplement", "frequency", "created_at"]
    raw_id_fields = ["version", "supplement"]


@admin.register(ProtocolAiJob)
class ProtocolAiJobAdmin(admin.ModelAdmin):
    list_display = ["id", "customer_profile", "name", "status", "attempt_count", "created_at"]
    list_filter = ["status"]
    search_fields = ["name"]
    raw_id_fields = ["customer_profile", "requested_by"]


@admin.register(AiRecommendation)
class AiRecommendationAdmin(admin.ModelAdmin):
    list_display = ["id", "customer_profile", "name", "model", "status", "created_at"]
    list_filter = ["status"]
    search_fields = ["name", "model"]
    raw_id_fields = ["job", "customer_profile", "protocol_version"]


@admin.register(AiRecommendationItem)
class AiRecommendationItemAdmin(admin.ModelAdmin):
    list_display = ["id", "recommendation", "supplement", "origin", "decision"]
    list_filter = ["origin", "decision"]
    raw_id_fields = ["recommendation", "supplement"]
