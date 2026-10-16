from django.contrib import admin
from django.http import HttpRequest

from accounts.verifications.models import PhoneVerification


@admin.register(PhoneVerification)
class PhoneVerificationAdmin(admin.ModelAdmin):
    readonly_fields = [
        "id",
        "phone",
        "purpose",
        "counter",
        "retry_count",
        "expires_at",
        "verified_at",
        "lockout_expires_at",
        "is_active",
        "created_at",
        "updated_at",
    ]
    list_display = ["id", "phone", "purpose", "is_system", "is_active", "expires_at"]
    list_filter = ["purpose", "is_system", "is_active"]
    search_fields = ["phone", "id"]
    list_per_page = 25

    def has_add_permission(self, request: HttpRequest):
        return False
