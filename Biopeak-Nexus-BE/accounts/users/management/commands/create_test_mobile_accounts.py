from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import IntegrityError, transaction

from accounts.utils import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Create the eight allowlisted local OTP test accounts."

    def handle(self, *args, **options):
        if not getattr(settings, "DEBUG", False):
            raise CommandError("This command is allowed only when DEBUG=True.")

        phones = getattr(settings, "LOCAL_TEST_OTP_PHONES", [])
        if len(phones) != 8 or len(set(phones)) != 8:
            raise CommandError("Settings must define exactly eight unique test phone numbers.")

        created_count = 0
        for index, phone in enumerate(phones, start=1):
            email = f"biopeak.test{index}@example.invalid"
            try:
                with transaction.atomic():
                    user, created = User.objects.get_or_create(
                        phone=phone,
                        defaults={
                            "email": email,
                            "first_name": f"BiopeakTest{index}",
                            "last_name": "Account",
                            "is_active": True,
                        },
                    )
                    if created:
                        created_count += 1
                    elif not user.is_active:
                        user.is_active = True
                        user.save(update_fields=["is_active", "updated_at"])
            except IntegrityError as exc:
                raise CommandError(
                    f"Could not create test account for {phone}; check existing unique email/phone values."
                ) from exc

            self.stdout.write(
                f"{ 'Created' if created else 'Exists' }: {phone} ({email if not user.email else user.email})"
            )

        self.stdout.write(self.style.SUCCESS(
            f"Done. {created_count} new test account(s); {len(phones)} allowlisted accounts available."
        ))
