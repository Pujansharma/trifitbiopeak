import hashlib

from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory, force_authenticate

from accounts.customers.models import Customer, CustomerProfile
from accounts.models import UserAccount
from accounts.users.models import User
from accounts.utils.constants import UserType
from compliance.consent_journey.models import (
    CONSENT_FORM_HASH_IMMUTABLE_MESSAGE,
    ConsentForm,
    CustomerConsentHistory,
)
from compliance.consent_journey.serializers import (
    CONSENT_ACCEPT_RETRY_MESSAGE,
    CONSENT_FORM_PDF_ONLY_MESSAGE,
    AcceptConsentFormSerializer,
    ConsentFormUploadSerializer,
    UpdateMarketingConsentSerializer,
)
from compliance.consent_journey.utils.constants import (
    REQUIRED_TRUE_CONSENT_NAMES,
    ConsentDecisionType,
    ConsentName,
)
from compliance.consent_journey.views import (
    AcceptConsentFormView,
    ConsentFormUploadView,
    UpdateMarketingConsentView,
)


def set_account_type(user, account_type):
    account, _created = UserAccount.objects.get_or_create(user=user)
    if account.account_type != account_type:
        account.account_type = account_type
        account.save(update_fields=["account_type"])


def create_admin_user(email="consent-admin@example.com"):
    user = User.objects.create_user(email=email)
    UserAccount.objects.create(user=user, account_type=UserType.ADMIN)
    return user


def create_customer_profile(email="consent-customer@example.com"):
    user = User.objects.create_user(email=email)
    customer = Customer.objects.create(user=user, contact_email=email)
    profile = CustomerProfile.objects.create(
        customer=customer,
        first_name="Pat",
        last_name="Ient",
        is_main=True,
    )
    set_account_type(user, UserType.CUSTOMER)
    return profile


def pdf_upload(name="consent.pdf", content=b"%PDF-1.4 consent"):
    return SimpleUploadedFile(name, content, content_type="application/pdf")


def create_consent_form(version="1.0", content=b"%PDF-1.4 consent"):
    uploaded = pdf_upload(f"{version}.pdf", content=content)
    return ConsentForm.objects.create(
        consent_form=uploaded,
        version=version,
        consent_form_hash=hashlib.sha256(content).hexdigest(),
    )


class ConsentFormUploadTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.admin = create_admin_user()
        self.customer_profile = create_customer_profile()

    def test_upload_rejects_non_pdf(self):
        serializer = ConsentFormUploadSerializer(
            data={
                "consent_form": SimpleUploadedFile(
                    "notes.txt", b"not a pdf", content_type="text/plain"
                ),
                "version": "1.0",
            }
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("consent_form", serializer.errors)
        self.assertIn(
            CONSENT_FORM_PDF_ONLY_MESSAGE,
            str(serializer.errors["consent_form"]),
        )

    def test_upload_accepts_pdf(self):
        content = b"%PDF-1.4 consent"
        serializer = ConsentFormUploadSerializer(
            data={"consent_form": pdf_upload(content=content), "version": "1.0"}
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        form = serializer.save()
        self.assertEqual(form.version, "1.0")
        self.assertEqual(form.consent_form_hash, hashlib.sha256(content).hexdigest())
        self.assertNotIn("consent_form_hash", serializer.data)

    def test_upload_hash_immutable_after_create(self):
        form = create_consent_form("1.0")
        form.consent_form_hash = "0" * 64
        with self.assertRaises(DjangoValidationError) as raised:
            form.save()
        self.assertIn(CONSENT_FORM_HASH_IMMUTABLE_MESSAGE, str(raised.exception))

    def test_upload_admin_only(self):
        request = self.factory.post(
            "/compliance/consent-journey/upload-consent-form/",
            {"consent_form": pdf_upload(), "version": "2.0"},
            format="multipart",
        )
        force_authenticate(request, user=self.customer_profile.customer.user)
        response = ConsentFormUploadView.as_view()(request)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AcceptConsentFormTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_customer_profile()
        self.other_profile = create_customer_profile(
            email="consent-other@example.com"
        )
        self.consent_form = create_consent_form("1.0")

    def test_accept_idempotent(self):
        serializer = AcceptConsentFormSerializer(
            data={
                "marketing_communications": True,
                "consent_form_version": "1.0",
            },
            context={"customer_profile": self.profile},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        first = serializer.save()
        self.assertEqual(len(first), 4)

        again = AcceptConsentFormSerializer(
            data={
                "marketing_communications": False,
                "consent_form_version": "1.0",
            },
            context={"customer_profile": self.profile},
        )
        self.assertTrue(again.is_valid(), again.errors)
        second = again.save()
        self.assertEqual(
            CustomerConsentHistory.objects.filter(customer_profile=self.profile).count(),
            4,
        )
        self.assertEqual(len(second), 4)

    def test_accept_incomplete_race_returns_validation_error(self):
        for consent_name in REQUIRED_TRUE_CONSENT_NAMES:
            CustomerConsentHistory.objects.create(
                customer_profile=self.profile,
                consent_name=consent_name,
                value=True,
                consent_form_version=self.consent_form,
                decision_type=ConsentDecisionType.INITIAL_CONFIRMATION,
            )

        serializer = AcceptConsentFormSerializer(
            data={
                "marketing_communications": True,
                "consent_form_version": "1.0",
            },
            context={"customer_profile": self.profile},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        with self.assertRaises(DRFValidationError) as raised:
            serializer.save()
        self.assertIn(CONSENT_ACCEPT_RETRY_MESSAGE, str(raised.exception.detail))

    def test_accept_other_profile_not_found(self):
        request = self.factory.post(
            f"/compliance/consent-journey/accept-consent-form/{self.other_profile.pk}/",
            {
                "marketing_communications": True,
                "consent_form_version": "1.0",
            },
            format="json",
        )
        force_authenticate(request, user=self.profile.customer.user)
        response = AcceptConsentFormView.as_view()(
            request, customer_profile_id=self.other_profile.pk
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class UpdateMarketingConsentTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.profile = create_customer_profile()
        self.consent_form = create_consent_form("1.0")
        accept = AcceptConsentFormSerializer(
            data={
                "marketing_communications": True,
                "consent_form_version": "1.0",
            },
            context={"customer_profile": self.profile},
        )
        accept.is_valid(raise_exception=True)
        accept.save()

    def test_mac_same_value_is_idempotent(self):
        before = CustomerConsentHistory.objects.filter(
            customer_profile=self.profile,
            consent_name=ConsentName.MARKETING_COMMUNICATIONS,
        ).count()
        serializer = UpdateMarketingConsentSerializer(
            data={"value": True, "consent_form_version": "1.0"},
            context={"customer_profile": self.profile},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        row = serializer.save()
        after = CustomerConsentHistory.objects.filter(
            customer_profile=self.profile,
            consent_name=ConsentName.MARKETING_COMMUNICATIONS,
        ).count()
        self.assertEqual(before, after)
        self.assertTrue(row.value)

    def test_mac_value_change_appends(self):
        before = CustomerConsentHistory.objects.filter(
            customer_profile=self.profile,
            consent_name=ConsentName.MARKETING_COMMUNICATIONS,
        ).count()
        serializer = UpdateMarketingConsentSerializer(
            data={"value": False, "consent_form_version": "1.0"},
            context={"customer_profile": self.profile},
        )
        self.assertTrue(serializer.is_valid(), serializer.errors)
        row = serializer.save()
        after = CustomerConsentHistory.objects.filter(
            customer_profile=self.profile,
            consent_name=ConsentName.MARKETING_COMMUNICATIONS,
        ).count()
        self.assertEqual(before + 1, after)
        self.assertFalse(row.value)

    def test_mac_update_view_returns_201(self):
        request = self.factory.post(
            f"/compliance/consent-journey/update-MAC-consent/{self.profile.pk}/",
            {"value": False, "consent_form_version": "1.0"},
            format="json",
        )
        force_authenticate(request, user=self.profile.customer.user)
        response = UpdateMarketingConsentView.as_view()(
            request, customer_profile_id=self.profile.pk
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
