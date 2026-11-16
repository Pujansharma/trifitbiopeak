from django.conf import settings
from django.db.models import TextChoices
from django.template.loader import get_template

from accounts.customers.models import CustomerProfileAddress
from core.utils.emails import send_templated_email
from leads.models import Lead
from leads.utils.constants import (
    OPS_ONBOARDING_EMAIL_EMPTY,
    OPS_ONBOARDING_EMAIL_TO,
    LeadPackages,
    OpsOnboardingActionPriority,
    OpsOnboardingConsultationMode,
    OpsOnboardingPaymentStatus,
    OpsOnboardingTypeformStatus,
)

OPS_ONBOARDING_EMAIL_TEMPLATE = "mails/ops_onboarding_email.html"


def display_or_empty(value):
    if value is None:
        return OPS_ONBOARDING_EMAIL_EMPTY
    if isinstance(value, str) and not value.strip():
        return OPS_ONBOARDING_EMAIL_EMPTY
    return value


def format_date_or_empty(value):
    if value is None:
        return OPS_ONBOARDING_EMAIL_EMPTY
    return value.isoformat()


def format_lead_client_name(lead: Lead):
    full_name = " ".join(
        part for part in [lead.first_name, lead.last_name] if part
    ).strip()
    return full_name or OPS_ONBOARDING_EMAIL_EMPTY


def format_lead_package_names(lead: Lead):
    packages = lead.packages or []
    if not packages:
        return OPS_ONBOARDING_EMAIL_EMPTY
    label_by_code = dict(LeadPackages.choices)
    return ", ".join(label_by_code.get(code, code) for code in packages)


def get_lead_address_parts(lead: Lead):
    profile = lead.customer_profile
    if profile is None:
        return None, None, None

    address = (
        CustomerProfileAddress.objects.filter(customer_profile=profile)
        .order_by("-is_default", "-created_at")
        .first()
    )
    if address is None:
        return None, None, None

    line_parts = [
        part
        for part in [address.line_1, address.line_2, address.state, address.pincode]
        if part
    ]
    street = ", ".join(line_parts)
    return street, address.city, address.country


def format_city_country(city, country):
    parts = [part for part in [city, country] if part]
    if not parts:
        return OPS_ONBOARDING_EMAIL_EMPTY
    return ", ".join(parts)


def format_choice_label(value: str | None, choices: type[TextChoices]) -> str:
    if value is None:
        return OPS_ONBOARDING_EMAIL_EMPTY
    if isinstance(value, str) and not value.strip():
        return OPS_ONBOARDING_EMAIL_EMPTY
    return choices(value).label


def format_boolean_display(value):
    if value is None:
        return OPS_ONBOARDING_EMAIL_EMPTY
    return "Yes" if value else "No"


def format_additional_contacts(contacts):
    if not contacts:
        return []
    return [
        {
            "name": display_or_empty(contact.get("name")),
            "relationship": display_or_empty(contact.get("relationship")),
            "email": display_or_empty(contact.get("email")),
            "phone": display_or_empty(contact.get("phone")),
        }
        for contact in contacts
    ]


def build_ops_onboarding_email_context(lead: Lead, triggered_by, payload: dict):
    street, city, country = get_lead_address_parts(lead)
    clinic_name = lead.home_center.name if lead.home_center else None
    triggered_by_name = triggered_by.get_full_name() or triggered_by.email
    phone = str(lead.phone) if lead.phone else None

    return {
        "client_name": format_lead_client_name(lead),
        "client_email": display_or_empty(lead.email),
        "client_phone": display_or_empty(phone),
        "client_date_of_birth": format_date_or_empty(lead.date_of_birth),
        "client_address": display_or_empty(street),
        "client_city_country": format_city_country(city, country),
        "package_name": format_lead_package_names(lead),
        "package_value": display_or_empty(payload.get("package_value")),
        "clinic_name": display_or_empty(clinic_name),
        "payment_status": format_choice_label(
            payload.get("payment_status"), OpsOnboardingPaymentStatus
        ),
        "therapy_paid_count": display_or_empty(payload.get("therapy_paid_count")),
        "therapy_paid_notes": display_or_empty(payload.get("therapy_paid_notes")),
        "therapy_complimentary_count": display_or_empty(
            payload.get("therapy_complimentary_count")
        ),
        "therapy_complimentary_notes": display_or_empty(
            payload.get("therapy_complimentary_notes")
        ),
        "onboarding_status": format_choice_label(
            payload.get("onboarding_status"), OpsOnboardingTypeformStatus
        ),
        "consultation_mode": format_choice_label(
            payload.get("consultation_mode"), OpsOnboardingConsultationMode
        ),
        "preferred_consultation_date": format_date_or_empty(
            payload.get("preferred_consultation_date")
        ),
        "preferred_consultation_time": display_or_empty(
            payload.get("preferred_consultation_time")
        ),
        "preferred_consultation_notes": display_or_empty(
            payload.get("preferred_consultation_notes")
        ),
        "preferred_home_assessment_notes": display_or_empty(
            payload.get("preferred_home_assessment_notes")
        ),
        "preferred_clinic_assessment_notes": display_or_empty(
            payload.get("preferred_clinic_assessment_notes")
        ),
        "tentative_assessment_date": format_date_or_empty(
            payload.get("tentative_assessment_date")
        ),
        "test_kit_delivery": format_boolean_display(payload.get("test_kit_delivery")),
        "special_instruction_notes": display_or_empty(
            payload.get("special_instruction_notes")
        ),
        "additional_contacts": format_additional_contacts(
            payload.get("additional_contacts")
        ),
        "action_note": display_or_empty(payload.get("action_note")),
        "action_priority": format_choice_label(
            payload.get("action_priority"), OpsOnboardingActionPriority
        ),
        "lead_unique_id": display_or_empty(lead.unique_id),
        "triggered_by_name": display_or_empty(triggered_by_name),
    }


def build_ops_onboarding_email_subject(lead: Lead):
    client_name = format_lead_client_name(lead)
    package_name = format_lead_package_names(lead)
    return f"New Client Onboarding | {client_name} | {package_name}"


def get_ops_onboarding_email_template(lead: Lead, triggered_by, payload: dict):
    context = build_ops_onboarding_email_context(lead, triggered_by, payload)
    return get_template(OPS_ONBOARDING_EMAIL_TEMPLATE).render(context)


def send_ops_onboarding_email(lead: Lead, triggered_by, payload: dict):
    subject = build_ops_onboarding_email_subject(lead)
    template = get_ops_onboarding_email_template(lead, triggered_by, payload)
    send_templated_email(
        subject,
        template,
        OPS_ONBOARDING_EMAIL_TO,
        from_email=settings.DEFAULT_FROM_EMAIL,
        cc=[triggered_by.email],
        send_now=True,
    )
