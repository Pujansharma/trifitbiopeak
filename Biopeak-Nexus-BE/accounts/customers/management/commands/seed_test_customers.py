from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.users.models import User
from accounts.customers.models import Customer, CustomerProfile
from accounts.customers.utils.db import create_customer_user_account


class Command(BaseCommand):
    help = "Create 10 test customers for development"

    def handle(self, *args, **options):
        if not settings.DEBUG or settings.SETTINGS_MODULE != "core.settings.development":
            raise CommandError("Only allowed in an isolated development environment.")

        with transaction.atomic():
            for i in range(1, 11):
                phone = f"+9199999001{i:02d}"
                email = f"biopeak-test-{i:02d}@example.com"

                user = User.objects.filter(phone=phone).first()

                if user and user.email != email:
                    raise CommandError(
                        f"Phone {phone} already belongs to another user."
                    )

                if user is None:
                    if User.objects.filter(email=email).exists():
                        raise CommandError(
                            f"Email {email} is already registered."
                        )

                    user = User.objects.create_user(
                        email=email,
                        phone=phone,
                        password=None,
                        first_name=f"Test{i:02d}",
                        last_name="Customer",
                        is_active=True,
                    )

                customer, _ = Customer.objects.get_or_create(
                    user=user,
                    defaults={"contact_email": email},
                )

                if not customer.profiles.filter(is_main=True).exists():
                    CustomerProfile.objects.create(
                        customer=customer,
                        first_name=f"Test{i:02d}",
                        last_name="Customer",
                        is_main=True,
                    )

                create_customer_user_account(customer)

                self.stdout.write(f"Ready: {phone}")

        self.stdout.write(
            self.style.SUCCESS("10 test customer accounts are ready.")
        )