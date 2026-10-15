"""Read-only readiness report for isolated direct-phone and wearables staging tests."""

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection

from accounts.customers.models import Customer, CustomerProfile, CustomerProfileFeature
from accounts.models import UserAccount
from accounts.organizations.utils.constants import FeatureTabOptions
from accounts.users.models import User
from accounts.utils.constants import UserType
from accounts.verifications.utils.direct_login_testing import (
    TEST_LOGIN_CONTACTS,
    TEST_LOGIN_SETTINGS_MODULES,
    direct_phone_login_testing_is_enabled,
)


class Command(BaseCommand):
    help = "Check staging test identities, permissions, feature flags and ROOK tables."

    def handle(self, *args, **options):
        if settings.SETTINGS_MODULE not in TEST_LOGIN_SETTINGS_MODULES:
            raise CommandError("Use development/staging, never production.")

        login_enabled = direct_phone_login_testing_is_enabled()
        wearables_enabled = getattr(settings, "WEARABLES_ENABLED", False)
        profile_gate = getattr(settings, "WEARABLES_REQUIRE_PROFILE_FEATURE", False)
        timeline_enabled = getattr(settings, "TIMELINE_ENABLED", False)

        self.stdout.write(f"Settings module: {settings.SETTINGS_MODULE}")
        self.stdout.write(f"Restricted direct login enabled: {login_enabled}")
        self.stdout.write(f"Wearables globally enabled: {wearables_enabled}")
        self.stdout.write(f"Wearables profile feature gate: {profile_gate}")
        self.stdout.write(f"Timeline enabled: {timeline_enabled}")
        self.stdout.write(
            f"ROOK server credentials configured: "
            f"{bool(getattr(settings, 'ROOK_CLIENT_UUID', '') and getattr(settings, 'ROOK_SECRET_KEY', ''))}"
        )

        expected_models = [
            User,
            UserAccount,
            Customer,
            CustomerProfile,
            CustomerProfileFeature,
            *apps.get_app_config("wearables").get_models(),
        ]
        existing_tables = set(connection.introspection.table_names())
        missing_tables = sorted(
            model._meta.db_table
            for model in expected_models
            if model._meta.db_table not in existing_tables
        )
        if missing_tables:
            self.stdout.write(self.style.ERROR("Missing database tables:"))
            for table_name in missing_tables:
                self.stdout.write(f"  - {table_name}")
            raise CommandError(
                "Review/create the required Django migrations locally, deploy them, "
                "and run migrate against your dedicated staging Aiven database."
            )

        failures = []
        for phone, email in TEST_LOGIN_CONTACTS:
            user = User.objects.filter(
                phone=phone, email__iexact=email, is_active=True,
                is_staff=False, is_superuser=False,
            ).first()
            if user is None:
                failures.append(f"{phone}: missing/inactive synthetic User")
                continue
            if not UserAccount.objects.filter(
                user=user, account_type=UserType.CUSTOMER
            ).exists():
                failures.append(f"{phone}: missing CUSTOMER account role")
                continue
            profile = CustomerProfile.objects.filter(
                customer__user=user, is_main=True
            ).first()
            if profile is None:
                failures.append(f"{phone}: missing main CustomerProfile")
                continue
            if profile_gate:
                enabled_tabs = CustomerProfileFeature.objects.filter(
                    customer_profile=profile
                ).values_list("enabled_tabs", flat=True).first()
                if FeatureTabOptions.WEARABLES not in (enabled_tabs or []):
                    failures.append(f"{phone}: missing wearables profile feature")
                    continue
            self.stdout.write(self.style.SUCCESS(f"OK {phone} - profile {profile.pk}"))

        for message in failures:
            self.stdout.write(self.style.ERROR(message))
        if failures or not login_enabled or not wearables_enabled:
            raise CommandError(
                "Staging is not ready. Review the settings above, then seed the "
                "test accounts and rerun this command."
            )
        self.stdout.write(
            self.style.SUCCESS(
                "Ready for authenticated /devices/ and /health/* GET smoke tests. "
                "Actual ROOK data/connection requires approved ROOK credentials, "
                "consent and a connected device."
            )
        )
