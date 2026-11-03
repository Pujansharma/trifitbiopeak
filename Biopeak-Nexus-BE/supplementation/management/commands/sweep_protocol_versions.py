from django.core.management.base import BaseCommand

from supplementation.utils.version_status import sweep_protocol_versions


class Command(BaseCommand):
    help = (
        "Expire protocol versions whose end date has passed, then activate "
        "scheduled versions whose start date has arrived."
    )

    def handle(self, *args, **options):
        expired_count, activated_count = sweep_protocol_versions()
        self.stdout.write(
            self.style.SUCCESS(
                f"Expired {expired_count} protocol version(s). "
                f"Activated {activated_count} protocol version(s)."
            )
        )
