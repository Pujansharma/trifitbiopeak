from django.utils import timezone
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.views import APIView

from external.models import ServiceAccount
from external.utils.helper import hash_service_account_token


class ExternalAPIKeyPermission(BasePermission):
    message = "API key is either missing, invalid, or expired."

    def has_permission(self, request: Request, view: APIView) -> bool:
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            raise PermissionDenied(detail=self.message, code="api_key_invalid")
        service_account = ServiceAccount.objects.filter(
            is_active=True, hashed_token=hash_service_account_token(api_key),
        ).first()
        if not service_account or (service_account.expires_at and service_account.expires_at <= timezone.now()):
            raise PermissionDenied(detail=self.message, code="api_key_invalid")
        setattr(request, "service_account", service_account)
        return True
