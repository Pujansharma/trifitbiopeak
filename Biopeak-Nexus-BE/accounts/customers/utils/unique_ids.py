from django.utils import timezone

from sequences.utils import get_next_sequence


def generate_customer_profile_unique_id(when=None):
    moment = timezone.localtime(when)
    year_month = moment.strftime("%y%m")
    sequence_value = get_next_sequence(
        name="customer_profiles",
        fill_length=3,
    )
    return f"BP-{year_month}{sequence_value}"
