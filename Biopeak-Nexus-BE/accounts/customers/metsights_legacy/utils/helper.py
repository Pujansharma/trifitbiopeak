from django.db.models import QuerySet

from accounts.customers.metsights_legacy.utils.diagnostics_attachments import (
    build_diagnostics_attachments_for_profile,
)
from accounts.customers.models import CustomerProfile
from core.utils.log import logger
from integrations.metsights.models import MetsightsProfile
from integrations.metsights.utils.sdk import (
    METSIGHTS_API_KEY,
    export_record_reports,
    get_consolidated_precision_report,
    get_files_for_report,
    get_metsights_report,
    get_profile_records,
    get_profile_reports,
    get_record,
    get_record_documents,
    get_record_personalised_plan,
    get_trends_for_report,
)


def get_metsights_records_for_customer(customer: CustomerProfile):
    logger.info(f"MetSights records requested: customer_profile_id={customer.pk}")
    metsights_profile = MetsightsProfile.objects.filter(customer_profile=customer).first()
    if metsights_profile is None:
        logger.warning(f"MetSights profile not linked: customer_profile_id={customer.pk}")
        return None
    records = get_profile_records(metsights_profile.profile_id)
    logger.info(f"MetSights records response: customer_profile_id={customer.pk}, available={records is not None}")
    return records


def get_metsights_reports_for_customer(
        customer: CustomerProfile, *, subscription_id: str | None = None,
):
    metsights_profile = MetsightsProfile.objects.filter(customer_profile=customer).first()
    if metsights_profile is None:
        return None
    reports, error = get_profile_reports(
        metsights_profile.profile_id,
        subscription_id=subscription_id,
        api_key=METSIGHTS_API_KEY,
    )
    if error:
        return None
    return reports


def get_metsights_record_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    logger.info(f"MetSights record requested: record_id={record_id}")
    record = get_record(record_id)
    if record is None:
        logger.warning(f"MetSights record unavailable: record_id={record_id}")
        return None
    remote_profile = record["profile"]
    remote_profile_identifier = remote_profile["id"]
    remote_profile_identifier = str(remote_profile_identifier)
    metsights_profile = MetsightsProfile.objects.filter(
        customer_profile__in=customer_profiles,
        profile_id=remote_profile_identifier,
    ).first()
    if metsights_profile is None:
        logger.warning(f"MetSights record ownership check failed: record_id={record_id}")
        return None
    logger.info(
        f"MetSights record ownership verified: customer_profile_id={metsights_profile.pk}, record_id={record_id}"
    )
    return record


def get_customer_profile_for_metsights_record(
        customer_profiles: QuerySet[CustomerProfile], record: dict,
):
    remote_profile = record.get("profile") or {}
    remote_profile_identifier = remote_profile.get("id")
    if remote_profile_identifier is None:
        return None
    metsights_profile = MetsightsProfile.objects.filter(
        customer_profile__in=customer_profiles,
        profile_id=str(remote_profile_identifier),
    ).select_related("customer_profile").first()
    if metsights_profile is None:
        return None
    return metsights_profile.customer_profile


def get_metsights_personalised_plan_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    return get_record_personalised_plan(record_id)


def get_metsights_attachments_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str, *,
        category_type: str | None = None, module_type: str | None = None,
        file_type: str | None = None,
):
    logger.info(f"MetSights attachments requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    documents = get_record_documents(
        record_id,
        category_type=category_type,
        module_type=module_type,
        file_type=file_type,
    )
    customer_profile = get_customer_profile_for_metsights_record(
        customer_profiles, record
    )
    diagnostics_attachments = build_diagnostics_attachments_for_profile(
        customer_profile,
        category_type=category_type,
    )
    if documents is None and not diagnostics_attachments:
        logger.info(
            f"MetSights attachments response: record_id={record_id}, available=False"
        )
        return None
    combined = list(documents or []) + diagnostics_attachments
    logger.info(
        f"MetSights attachments response: record_id={record_id}, "
        f"metsights={len(documents or [])}, diagnostics={len(diagnostics_attachments)}"
    )
    return combined


def get_metsights_report_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    logger.info(f"MetSights report requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    data, error = get_metsights_report(record_id, METSIGHTS_API_KEY)
    logger.info(
        f"MetSights report response: record_id={record_id}, available={data is not None}, failed={bool(error)}")
    return data


def get_metsights_consolidated_report_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    logger.info(f"MetSights consolidated report requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    data, error = get_consolidated_precision_report(record_id, METSIGHTS_API_KEY)
    logger.info(
        f"MetSights consolidated report response: record_id={record_id}, available={data is not None}, failed={bool(error)}")
    return data


def get_metsights_trends_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    logger.info(f"MetSights trends requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    data, error = get_trends_for_report(record_id, METSIGHTS_API_KEY)
    logger.info(
        f"MetSights trends response: record_id={record_id}, available={data is not None}, failed={bool(error)}")
    return data


def get_metsights_report_files_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str,
):
    logger.info(f"MetSights report files requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    response_data, error = get_files_for_report(record_id, METSIGHTS_API_KEY)
    if error:
        logger.warning(f"MetSights report files request failed: record_id={record_id}")
        return None
    files = response_data.get('data')
    logger.info(
        f"MetSights report files response: record_id={record_id}, available={files is not None}")
    return files


def export_metsights_reports_for_customer(
        customer_profiles: QuerySet[CustomerProfile], record_id: str, email: str,
):
    logger.info(f"MetSights report export requested: record_id={record_id}")
    record = get_metsights_record_for_customer(customer_profiles, record_id)
    if record is None:
        return None
    response_data = export_record_reports(record_id, email)
    logger.info(
        f"MetSights report export response: record_id={record_id}, accepted={response_data is not None}")
    return response_data
