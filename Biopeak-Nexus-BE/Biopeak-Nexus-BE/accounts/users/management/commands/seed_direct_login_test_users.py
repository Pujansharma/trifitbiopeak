"""Seed the eight allowlisted customer accounts in isolated dev/staging."""

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.customers.models import (
    Customer,
    CustomerProfile,
    CustomerProfileFeature,
)
from accounts.customers.utils.db import create_customer_user_account
from accounts.organizations.utils.constants import FeatureTabOptions
from accounts.users.models import User
from accounts.verifications.utils.direct_login_testing import (
    TEST_LOGIN_CONTACTS,
    direct_phone_login_testing_is_enabled,
)


class Command(BaseCommand):
    help = "Create/verify eight restricted synthetic customer accounts for ROOK staging tests."

    def add_arguments(self, parser):
        parser.add_argument(
            "--confirm-staging",
            action="store_true",
            help="Confirm you inspected the Aiven DB target and it is an isolated staging DB.",
        )

    def handle(self, *args, **options):
        if not direct_phone_login_testing_is_enabled():
            raise CommandError(
                "Synthetic test login must be explicitly enabled in development or "
                "staging with a configured key of at least 32 characters."
            )
        if (
            settings.SETTINGS_MODULE == "core.settings.staging"
            and not options["confirm_staging"]
        ):
            raise CommandError(
                "Staging seeding requires --confirm-staging after checking the "
                "database is NOT production and contains no client records."
            )

        with transaction.atomic():
            for account_number, (phone, email) in enumerate(TEST_LOGIN_CONTACTS, start=1):
                # PhoneNumberSerializerField canonicalizes +919999900101
                # to +91-9999900101. Previous seed releases used the compact
                # string; adopt matching synthetic users without duplicating them.
                compact_phone = phone.replace("-", "")
                user = User.objects.filter(email__iexact=email).first()
                reserved_phone_users = User.objects.filter(
                    phone__in=[phone, compact_phone]
                )
                if user is not None and (
                    user.phone not in {phone, compact_phone}
                    or not user.is_active
                    or user.is_staff
                    or user.is_superuser
                ):
                    raise CommandError(
                        f"Reserved test identity {email} conflicts with a real/inactive account."
                    )
                if user is None and reserved_phone_users.exists():
                    raise CommandError(f"Reserved test phone {compact_phone} is already in use.")
                if user is not None and reserved_phone_users.exclude(pk=user.pk).exists():
                    raise CommandError(f"Reserved test phone {compact_phone} is already in use.")

                if user is None:
                    user = User.objects.create_user(
                        email=email,
                        phone=phone,
                        password=None,
                        first_name=f"Test{account_number:02d}",
                        last_name="Customer",
                        is_active=True,
                    )
                    status = "created"
                elif user.phone != phone:
                    user.phone = phone
                    user.save(update_fields=["phone", "updated_at"])
                    status = "normalized existing test user"
                else:
                    status = "already exists"

                customer, _ = Customer.objects.get_or_create(
                    user=user,
                    defaults={"contact_email": email},
                )
                customer_profile = CustomerProfile.objects.filter(
                    customer=customer, is_main=True
                ).first()
                if customer_profile is None:
                    customer_profile = CustomerProfile.objects.create(
                        customer=customer,
                        first_name=f"Test{account_number:02d}",
                        last_name="Customer",
                        is_main=True,
                    )

                create_customer_user_account(customer)
                profile_feature, _ = CustomerProfileFeature.objects.get_or_create(
                    customer_profile=customer_profile
                )
                enabled_tabs = list(profile_feature.enabled_tabs or [])
                if FeatureTabOptions.WEARABLES not in enabled_tabs:
                    enabled_tabs.append(FeatureTabOptions.WEARABLES)
                    profile_feature.enabled_tabs = enabled_tabs
                    profile_feature.save(update_fields=["enabled_tabs", "updated_at"])

                self.stdout.write(
                    f"{status}: {phone}; customer profile ID: {customer_profile.pk}"
                )

        self.stdout.write(
            self.style.SUCCESS("Eight synthetic test customers are ready.")
        )
