from collections import defaultdict

from compliance.consent_journey.models import ConsentForm, CustomerConsentHistory
from compliance.consent_journey.utils.constants import (
    REQUIRED_TRUE_CONSENT_NAMES,
    ConsentName,
)


def get_latest_consent_form():
    return ConsentForm.objects.filter_active().order_by("-created_at").first()


def get_latest_consent_history_rows(customer_profile, latest_form=None):
    if latest_form is None:
        latest_form = get_latest_consent_form()
    if latest_form is None:
        return None
    rows = list(
        CustomerConsentHistory.objects.filter(
            customer_profile=customer_profile,
            consent_form_version_id=latest_form.version,
        )
        .order_by("consent_name", "-created_at")
        .distinct("consent_name")
    )
    if not rows:
        return None
    return rows


def consent_rows_satisfy_latest(rows):
    if not rows:
        return False
    by_name = {row.consent_name: row for row in rows}
    if set(by_name) != set(ConsentName.values):
        return False
    for consent_name in REQUIRED_TRUE_CONSENT_NAMES:
        if not by_name[consent_name].value:
            return False
    return True


def get_consent_history_queryset(customer_profile):
    return CustomerConsentHistory.objects.filter(
        customer_profile=customer_profile
    ).order_by("-created_at")


def build_latest_consent_history_map(rows):
    return {
        row.consent_name: {
            "consent_form_version": row.consent_form_version_id,
            "value": row.value,
        }
        for row in rows
    }


def build_consent_given_map_for_profiles(profile_ids, latest_form):
    if not profile_ids or latest_form is None:
        return {profile_id: False for profile_id in profile_ids}

    rows = CustomerConsentHistory.objects.filter(
        customer_profile_id__in=profile_ids,
        consent_form_version_id=latest_form.version,
    ).order_by("customer_profile_id", "consent_name", "-created_at").distinct(
        "customer_profile_id", "consent_name"
    )

    rows_by_profile = defaultdict(list)
    for row in rows:
        rows_by_profile[row.customer_profile_id].append(row)

    return {
        profile_id: consent_rows_satisfy_latest(rows_by_profile.get(profile_id, []))
        for profile_id in profile_ids
    }


def is_latest_consent_given(customer_profile, latest_form=None):
    if latest_form is None:
        latest_form = get_latest_consent_form()
    if latest_form is None:
        return False
    rows = get_latest_consent_history_rows(customer_profile, latest_form=latest_form)
    if rows is None:
        return False
    return consent_rows_satisfy_latest(rows)
