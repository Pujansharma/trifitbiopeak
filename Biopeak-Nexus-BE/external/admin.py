from django import forms
from django.contrib import admin, messages
from django.http import HttpRequest

from external.models import ServiceAccount
from external.utils.helper import generate_service_account_token, hash_service_account_token


@admin.register(ServiceAccount)
class ServiceAccountAdmin(admin.ModelAdmin):
    fields = ["id", "name", "is_active", "expires_at", "created_at", "updated_at"]
    readonly_fields = ["id", "created_at", "updated_at"]
    list_display = ["name", "is_active", "expires_at", "created_at"]
    list_filter = ["is_active"]
    search_fields = ["name"]

    def save_model(self, request: HttpRequest, obj: ServiceAccount, form: forms.ModelForm, change: bool) -> None:
        if not change:
            generated_token = generate_service_account_token()
            obj.hashed_token = hash_service_account_token(generated_token)
        super().save_model(request, obj, form, change)
        if not change:
            self.message_user(
                request, f"API key: {generated_token}. Copy it now; only its hash is stored.",
                level=messages.SUCCESS,
            )
