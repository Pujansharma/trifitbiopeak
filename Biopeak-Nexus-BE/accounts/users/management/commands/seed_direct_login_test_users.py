"""Seed eight local-only customer accounts for /auth/login-phone-direct/."""
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.customers.models import Customer, CustomerProfile
from accounts.customers.utils.db import create_customer_user_account
from accounts.users.models import User


class Command(BaseCommand):
    help = "Create 8 idempotent local customer accounts for direct-phone login testing."

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.SETTINGS_MODULE != "core.settings.development":
            raise CommandError("Only allowed with core.settings.development and DEBUG=True.")

        # Deliberately not routed through real SMS/OTP; these are synthetic local DB identities.
        with transaction.atomic():
            for n in range(1, 9):
                phone = f"+9199999001{n:02d}"
                email = f"biopeak-direct-test-{n:02d}@example.com"
                user = User.objects.filter(phone=phone).first()
                if user and user.email != email:
                    raise CommandError(f"Phone {phone} already belongs to another user; aborting.")
                if not user and User.objects.filter(email=email).exists():
                    raise CommandError(f"Email {email} already belongs to another phone; aborting.")
                if not user:
                    user = User.objects.create_user(
                        email=email, phone=phone, password=None,
                        first_name=f"Test{n:02d}", last_name="Customer", is_active=True,
                    )
                    status = "created"
                else:
                    status = "exists"
                customer, _ = Customer.objects.get_or_create(user=user, defaults={"contact_email": email})
                if not customer.profiles.filter(is_main=True).exists():
                    CustomerProfile.objects.create(
                        customer=customer, first_name=f"Test{n:02d}",
                        last_name="Customer", is_main=True,
                    )
                create_customer_user_account(customer)
                self.stdout.write(f"{status}: {phone} ({email})")
        self.stdout.write(self.style.SUCCESS("Eight local direct-login test customers are ready."))
