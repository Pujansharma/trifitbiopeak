from django.contrib import admin
from django.http import HttpRequest

from accounts.customers.models import (
    Customer,
    CustomerAssociateAssignment,
    CustomerCopilotSession,
    CustomerProfile,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    readonly_fields = ["created_at", "updated_at"]
    list_filter = ["is_active"]
    list_display = ["user_id", "user__phone", "contact_email", "created_at"]
    raw_id_fields = ["user"]
    search_fields = ["user__id", "user__phone", "contact_email"]
    list_per_page = 25


@admin.register(CustomerProfile)
class CustomerProfileAdmin(admin.ModelAdmin):
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "is_main",
        "is_onboarding_completed",
        "centers_count",
        "external_centers_count",
    ]
    list_display = [
        "id",
        "first_name",
        "last_name",
        "customer__contact_email",
        "is_main",
        "created_at",
    ]
    list_filter = ["is_main", "is_onboarding_completed"]
    raw_id_fields = ["customer", "created_by"]
    list_select_related = True
    list_per_page = 25


@admin.register(CustomerAssociateAssignment)
class CustomerAssociateAssignmentAdmin(admin.ModelAdmin):
    readonly_fields = ["id", "created_at", "updated_at"]
    list_filter = ["is_active"]
    list_per_page = 25
    list_display = ["id", "center", "customer_profile", "associate"]
    list_select_related = True
    raw_id_fields = ["customer_profile", "associate", "center", "created_by"]


@admin.register(CustomerCopilotSession)
class CustomerCopilotSessionAdmin(admin.ModelAdmin):
    readonly_fields = [
        "id",
        "customer_profile",
        "session_id",
        "is_active",
        "created_at",
        "updated_at",
    ]
    list_display = [
        "id",
        "customer_profile",
        "session_id",
        "is_active",
        "created_at",
    ]
    list_select_related = ["customer_profile"]
    list_per_page = 25
    actions = None
    search_fields = ['customer_profile__pk', 'session_id']

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_delete_permission(self, request, obj=None) -> bool:
        return False
