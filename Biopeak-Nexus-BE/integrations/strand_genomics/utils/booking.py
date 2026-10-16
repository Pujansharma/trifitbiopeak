"""Submit Strand products using their saved booking and patient dictionaries."""

from core.utils.log import logger
from integrations.strand_genomics.utils.sdk import create_booking_order, parse_strand_request_id
from programs.program_services.utils.helper import generate_file_hash
from programs.services.models import ResultRequest, ResultRequestFile
from programs.services.utils.constants import ResultRequestStatus


def strand_nutri_dna_booking(result_request: ResultRequest, request=None) -> tuple | None:
    if result_request.data.get("request_id"):
        result_request.is_submitted = True
        result_request.save(update_fields=["is_submitted", "updated_at"])
        result_request.status = ResultRequestStatus.PENDING
        return True, None
    configuration = result_request.product.provider.api.data or {}
    booking = result_request.data or {}
    profile = result_request.profile_data or {}
    required_values = {
        "client_id": configuration.get("client_id"),
        "client_secret": configuration.get("client_secret"),
        "refresh_token": configuration.get("refresh_token"),
        "logged_user_email": configuration.get("logged_user_email"),
        "kit_id": booking.get("kit_id"),
        "sample_collection_date": booking.get("sample_collection_date"),
        "full_name": profile.get("full_name"),
        "gender": profile.get("gender"),
        "date_of_birth": profile.get("date_of_birth"),
        "test_code": "SLS168009",
        "test_name": "NutriDNA",
    }
    missing_keys = [key for key, value in required_values.items() if value is None or value == ""]
    if missing_keys:
        result_request.failure_detail = f"Missing Strand NutriDNA booking values: {', '.join(missing_keys)}."
        logger.error(
            f"Strand NutriDNA booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    consent_request_file = ResultRequestFile.objects.filter(
        result_request=result_request, field_name="consent_file", is_active=True,
    ).first()
    if not consent_request_file:
        result_request.failure_detail = "Strand NutriDNA booking requires a consent file."
        logger.error(
            f"Strand NutriDNA booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    consent_document = consent_request_file.file
    result_request.data["consent_hash"] = generate_file_hash(consent_document)
    consent_url = request.build_absolute_uri(consent_document.url) if request else consent_document.url
    result_request.data["consent_url"] = consent_url
    response, error = create_booking_order(
        client_id=required_values["client_id"],
        client_secret=required_values["client_secret"],
        refresh_token=required_values["refresh_token"],
        reference_id=required_values["kit_id"],
        full_name=required_values["full_name"],
        gender=required_values["gender"],
        date_of_birth=required_values["date_of_birth"],
        collection_date=required_values["sample_collection_date"],
        logged_user_email=required_values["logged_user_email"],
        has_medical_consent="Yes",
        product_code=required_values["test_code"],
        product_name=required_values["test_name"],
        consent_file_url=consent_url,
    )
    if error:
        result_request.failure_detail = error
        logger.error(f"Strand NutriDNA booking failed: request={result_request.pk} reason={error}")
        return None
    identifier, error = parse_strand_request_id(response)
    if not identifier:
        result_request.failure_detail = error or "Strand NutriDNA booking response has no test_ref."
        logger.error(
            f"Strand NutriDNA booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    result_request.data["request_id"] = identifier
    result_request.is_submitted = True
    result_request.save(update_fields=["data", "is_submitted", "updated_at"])
    result_request.status = ResultRequestStatus.PENDING
    return True, None


def strand_genomic_health_insights_booking(result_request: ResultRequest, request=None) -> tuple | None:
    if result_request.data.get("request_id"):
        result_request.is_submitted = True
        result_request.save(update_fields=["is_submitted", "updated_at"])
        result_request.status = ResultRequestStatus.PENDING
        return True, None
    configuration = result_request.product.provider.api.data or {}
    booking = result_request.data or {}
    profile = result_request.profile_data or {}
    required_values = {
        "client_id": configuration.get("client_id"),
        "client_secret": configuration.get("client_secret"),
        "refresh_token": configuration.get("refresh_token"),
        "logged_user_email": configuration.get("logged_user_email"),
        "kit_id": booking.get("kit_id"),
        "sample_collection_date": booking.get("sample_collection_date"),
        "full_name": profile.get("full_name"),
        "gender": profile.get("gender"),
        "date_of_birth": profile.get("date_of_birth"),
        "test_code": "SLS168004",
        "test_name": "Genomic Health Insights",
    }

    missing_keys = [key for key, value in required_values.items() if value is None or value == ""]
    if missing_keys:
        result_request.failure_detail = f"Missing Strand Genomic Health Insights booking values: {', '.join(missing_keys)}."
        logger.error(
            f"Strand Genomic Health Insights booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    consent_request_file = ResultRequestFile.objects.filter(
        result_request=result_request, field_name="consent_file", is_active=True,
    ).first()
    if not consent_request_file:
        result_request.failure_detail = "Strand Genomic Health Insights booking requires a consent file."
        logger.error(
            f"Strand Genomic Health Insights booking stopped: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    consent_document = consent_request_file.file
    result_request.data["consent_hash"] = generate_file_hash(consent_document)
    consent_url = request.build_absolute_uri(consent_document.url) if request else consent_document.url
    result_request.data["consent_url"] = consent_url
    response, error = create_booking_order(
        client_id=required_values["client_id"],
        client_secret=required_values["client_secret"],
        refresh_token=required_values["refresh_token"],
        reference_id=required_values["kit_id"],
        full_name=required_values["full_name"],
        gender=required_values["gender"],
        date_of_birth=required_values["date_of_birth"],
        collection_date=required_values["sample_collection_date"],
        logged_user_email=required_values["logged_user_email"],
        has_medical_consent="Yes",
        product_code=required_values["test_code"],
        product_name=required_values["test_name"],
        consent_file_url=consent_url,
    )
    if error:
        result_request.failure_detail = error
        logger.error(f"Strand Genomic Health Insights booking failed: request={result_request.pk} reason={error}")
        return None
    identifier, error = parse_strand_request_id(response)
    if not identifier:
        result_request.failure_detail = error or "Strand Genomic Health Insights booking response has no test_ref."
        logger.error(
            f"Strand Genomic Health Insights booking failed: request={result_request.pk} reason={result_request.failure_detail}")
        return None
    result_request.data["request_id"] = identifier
    result_request.is_submitted = True
    result_request.save(update_fields=["data", "is_submitted", "updated_at"])
    result_request.status = ResultRequestStatus.PENDING
    return True, None
