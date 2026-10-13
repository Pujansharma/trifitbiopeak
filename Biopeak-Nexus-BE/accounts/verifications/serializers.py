from django.utils import timezone
from rest_framework import serializers

from accounts.customers.models import CustomerProfile
from accounts.models import UserAccount
from accounts.utils import get_user_model
from accounts.utils.constants import UserType
from accounts.verifications.utils.direct_login_testing import TEST_LOGIN_EMAIL_BY_PHONE
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

        otp_data, status = generate_otp_for_phone(phone, purpose)
        if not status:
            raise serializers.ValidationError(
                f"Too many OTP requests. Please try again after sometime."
            )
        return phone


class LoginOTPSerializer(BaseSerializer):
    phone = PhoneNumberSerializerField()
    otp = serializers.CharField(required=True, min_length=6, max_length=6)

    def validate(self, attrs):
        phone = attrs.get("phone")
        otp = attrs.get("otp")
        instance = PhoneVerification.objects.filter(
            phone__iexact=phone,
            expires_at__gte=timezone.localtime(),
            purpose=PhoneVerification.PURPOSE_LOGIN,
        ).first()
        if not instance:
            raise serializers.ValidationError({"otp": ["OTP is expired or invalid."]})
        is_valid = verify_otp(instance, otp)
        user = User.objects.filter(phone=instance.phone, is_active=True).first()
        if not user:
            raise serializers.ValidationError("User not allowed to login.")
        if not is_valid:
            raise serializers.ValidationError({"otp": ["OTP is incorrect."]})
        return perform_login_for_user(user)


class DirectPhoneLoginSerializer(BaseSerializer):
    """Only allow the eight seeded customer identities, never arbitrary users."""

    phone = PhoneNumberSerializerField()

    def validate(self, attrs):
        phone = attrs.get("phone")
        expected_email = TEST_LOGIN_EMAIL_BY_PHONE.get(phone)
        if expected_email is None:
            raise serializers.ValidationError(
                {"phone": ["Phone is not an authorized synthetic test identity."]}
            )

        user = User.objects.filter(
            phone__iexact=phone,
            email__iexact=expected_email,
            is_active=True,
            is_staff=False,
            is_superuser=False,
        ).first()
        if (
            user is None
            or not UserAccount.objects.filter(
                user=user, account_type=UserType.CUSTOMER
            ).exists()
            or not CustomerProfile.objects.filter(
                customer__user=user, is_main=True
            ).exists()
        ):
            raise serializers.ValidationError(
                {"phone": ["Test customer is not provisioned. Run the seed command."]}
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
