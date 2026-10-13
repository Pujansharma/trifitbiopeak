from hmac import compare_digest
from ipaddress import ip_address

from django.conf import settings
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.permissions import AllowAny
from rest_framework.throttling import ScopedRateThrottle

from accounts.serializers import TOTPVerifySerializer
from accounts.verifications.utils.direct_login_testing import (
    direct_phone_login_testing_is_enabled,
)
from core.utils.views.main import BaseCreateAPIView
from .serializers import (
    DirectPhoneLoginSerializer,
    RequestOTPSerializer,
    LoginOTPSerializer,
    VerifyOTPSerializer,
)


def _is_loopback(value):
    try:
        return ip_address(value).is_loopback
    except ValueError:
        return False


class RequestOTPView(BaseCreateAPIView):
    serializer_class = RequestOTPSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.send_response("OTP sent successfully.")


class LoginOTPView(BaseCreateAPIView):
    serializer_class = LoginOTPSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.send_response("Login successful.", data=serializer.validated_data)


class DirectPhoneLoginView(BaseCreateAPIView):
    """Restricted test login for eight synthetic accounts."""

    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "test_direct_phone_login"
    serializer_class = DirectPhoneLoginSerializer

    def post(self, request, *args, **kwargs):
        if not direct_phone_login_testing_is_enabled():
            raise NotFound("Not found.")

        # Header-free login is permitted ONLY for requests originating from
        # loopback to the local development server. Public staging requires a key.
        local_dev = (
            settings.SETTINGS_MODULE == "core.settings.development"
            and settings.DEBUG
            and request.get_host().split(":", 1)[0].lower()
            in {"localhost", "127.0.0.1", "[::1]"}
            and _is_loopback(request.META.get("REMOTE_ADDR", ""))
        )
        if not local_dev:
            supplied_key = request.headers.get("X-Test-Login-Key", "")
            configured_key = settings.TEST_PHONE_LOGIN_KEY
            if (
                not isinstance(configured_key, str)
                or len(configured_key) < 32
                or not compare_digest(supplied_key, configured_key)
            ):
                raise PermissionDenied("Test login key is invalid.")

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.send_response("Login successful.", data=serializer.validated_data)


class VerifyOTPView(BaseCreateAPIView):
    serializer_class = VerifyOTPSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.send_response(
            "Verification successful.", data=serializer.validated_data
        )


class ValidateTOTPView(BaseCreateAPIView):
    serializer_class = TOTPVerifySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return self.send_response(
            "Verification successful.", data=serializer.validated_data
        )
