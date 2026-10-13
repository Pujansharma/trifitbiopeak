from django.conf import settings
from django.utils import timezone
from rest_framework import serializers

from accounts.utils import get_user_model
from core.utils.authentication import perform_login_for_user
from core.utils.fields import PhoneNumberSerializerField
from core.utils.serializers import BaseSerializer
from .models import PhoneVerification
from .utils import code_valid
from .utils.helper import verify_otp, generate_otp_for_phone

User = get_user_model()


class RequestOTPSerializer(BaseSerializer):
    phone = PhoneNumberSerializerField()

    purpose = serializers.ChoiceField(
        choices=PhoneVerification.PURPOSE_CHOICES,
        default=PhoneVerification.PURPOSE_LOGIN,
        required=False,
    )

    def validate(self, attrs):
        phone = attrs.get("phone")
        purpose = attrs.get("purpose")
        if purpose == PhoneVerification.PURPOSE_LOGIN:
            user = User.objects.filter(phone__iexact=phone).first()
            if not user:
                raise serializers.ValidationError(
                    {"phone": ["Phone number is not registered."]}
                )
            if not user.is_active:
                raise serializers.ValidationError("User account inactive.")

        # Local fixed-OTP flow is opt-in and limited to allowlisted test accounts.
        # It is never enabled by default and should not be enabled in deployed environments.
        if (
            getattr(settings, "LOCAL_TEST_OTP_ENABLED", False)
            and getattr(settings, "DEBUG", False)
            and purpose == PhoneVerification.PURPOSE_LOGIN
            and phone.replace("-", "").replace(" ", "")
    in [
        p.replace("-", "").replace(" ", "")
        for p in getattr(settings, "LOCAL_TEST_OTP_PHONES", [])
    ]
        ):
            return attrs

        otp_data, status = generate_otp_for_phone(phone, purpose)
        if not status:
            raise serializers.ValidationError(
                "Too many OTP requests. Please try again after sometime."
            )
        return attrs



class LoginOTPSerializer(BaseSerializer):
    phone = PhoneNumberSerializerField()
    otp = serializers.CharField(required=True, min_length=6, max_length=6)

    def validate(self, attrs):
        phone = attrs.get("phone")
        otp = attrs.get("otp")

        # Temporary debugging for local fixed-OTP testing only.
        if (
            getattr(settings, "DEBUG", False)
            and getattr(settings, "LOCAL_TEST_OTP_ENABLED", False)
        ):
            print("\n--- LOCAL OTP DEBUG ---")
            print("OTP enabled:", getattr(settings, "LOCAL_TEST_OTP_ENABLED", False))
            print("DEBUG:", getattr(settings, "DEBUG", False))
            print("Phone received:", repr(phone))
            print(
                "Phone allowlist match:",
                phone in getattr(settings, "LOCAL_TEST_OTP_PHONES", []),
            )
            print(
                "OTP matches configured code:",
                otp == getattr(settings, "LOCAL_TEST_OTP_CODE", None),
            )
            print("-----------------------\n")

        # Local fixed OTP: allowlisted test accounts only.
        if (
            getattr(settings, "LOCAL_TEST_OTP_ENABLED", False)
            and getattr(settings, "DEBUG", False)
            and phone.replace("-", "").replace(" ", "")
    in [
        p.replace("-", "").replace(" ", "")
        for p in getattr(settings, "LOCAL_TEST_OTP_PHONES", [])
    ]
            and otp == getattr(settings, "LOCAL_TEST_OTP_CODE", None)
        ):
            user = User.objects.filter(
                phone__iexact=phone,
                is_active=True,
            ).first()

            if not user:
                raise serializers.ValidationError({
                    "phone": [
                        "Test account is missing or inactive. "
                        "Run the test-account command."
                    ]
                })

            return perform_login_for_user(user)

        # Existing normal OTP verification flow.
        instance = PhoneVerification.objects.filter(
            phone__iexact=phone,
            expires_at__gte=timezone.localtime(),
            purpose=PhoneVerification.PURPOSE_LOGIN,
        ).first()

        if not instance:
            raise serializers.ValidationError({
                "otp": ["OTP is expired or invalid."]
            })

        is_valid = verify_otp(instance, otp)

        user = User.objects.filter(
            phone__iexact=instance.phone,
            is_active=True,
        ).first()

        if not user:
            raise serializers.ValidationError(
                "User not allowed to login."
            )

        if not is_valid:
            raise serializers.ValidationError({
                "otp": ["OTP is incorrect."]
            })

        return perform_login_for_user(user)

class DirectPhoneLoginSerializer(BaseSerializer):
    """Temporary: phone-only login without OTP. Remove in a future release."""

    phone = PhoneNumberSerializerField()

    def validate(self, attrs):
        phone = attrs.get("phone")
        user = User.objects.filter(phone__iexact=phone, is_active=True).first()
        if not user:
            raise serializers.ValidationError(
                {"phone": ["Phone number is not registered."]}
            )
        return perform_login_for_user(user)


class VerifyOTPSerializer(BaseSerializer):
    phone = PhoneNumberSerializerField()
    otp = serializers.CharField(required=True, min_length=6, max_length=6)
    purpose = serializers.ChoiceField(
        choices=PhoneVerification.PURPOSE_CHOICES,
        default=PhoneVerification.PURPOSE_VERIFY,
        required=False,
    )

    def validate(self, attrs):
        phone = attrs.get("phone")
        otp = attrs.get("otp")
        purpose = attrs.get("purpose")

        instance = PhoneVerification.objects.filter(
            phone__iexact=phone,
            purpose=purpose,
            expires_at__gte=timezone.localtime(),
            is_active=True,
        ).first()

        if not instance:
            raise serializers.ValidationError({"otp": ["OTP is expired or invalid."]})

        is_valid = code_valid(
            secret=instance.secret, counter=instance.counter, code=otp
        )
        if not is_valid:
            raise serializers.ValidationError({"otp": ["OTP is incorrect."]})

        if purpose == PhoneVerification.PURPOSE_REGISTER:
            # Mark as verified but keep alive for CustomerRegistrationSerializer
            PhoneVerification.objects.filter(pk=instance.pk).update(
                verified_at=timezone.now(),
                secret=None,
                counter=0,
                retry_count=0,
            )
        else:
            # For non-registration purposes, deactivate fully
            verify_otp(instance, otp)

        attrs["instance"] = instance
        return attrs
