from typing import BinaryIO

import requests
from django.conf import settings

from accounts.users.utils.constants import Gender
from core.utils.log import logger

METSIGHTS_BASE_URL = getattr(settings, "METSIGHTS_BASE_URL", "https://api.metsights.com")

METSIGHTS_API_KEY = getattr(settings, "METSIGHTS_API_KEY", None)
METSIGHTS_REQUEST_ERROR = "MetSights request failed."
METSIGHTS_REPORT_UNAVAILABLE = "MetSights report is not available yet."


class Session(requests.Session):
    def __init__(self, api_key=METSIGHTS_API_KEY):
        super().__init__()
        self.headers.update({
            'X-API-KEY': api_key or ""
        })


GENDER_MAPPING = {
    Gender.MALE: "1",
    Gender.FEMALE: "2"
}


def download_external_file(file_url: str) -> tuple[tuple[BinaryIO | None, str | None], str | None]:
    response = requests.get(file_url, timeout=60, stream=True)
    if not response.ok:
        response.close()
        return (None, None), METSIGHTS_REPORT_UNAVAILABLE
    response.raw.decode_content = True
    return (response.raw, response.headers.get("Content-Type", "application/octet-stream")), None


def get_metsights_profile(phone):
    url = METSIGHTS_BASE_URL + "/profiles/"
    session = Session()
    response = session.get(url, params={
        'search': phone,
        'limit': 1
    })
    if not response.ok:
        logger.warning(f'Invalid response returned, {response.status_code}: {response.json()}')
        return None
    response_data = response.json()
    data = response_data.get('data')
    if not data:
        logger.warning("No profiles exist")
        return None
    return data[0].get('id')


def create_metsights_profile(
        phone, email, first_name, last_name, gender, age=None, date_of_birth=None
):
    profile_id = get_metsights_profile(phone)
    if profile_id:
        return {"data": {"id": profile_id}}
    url = METSIGHTS_BASE_URL + "/profiles/"
    session = Session()
    gender_value = GENDER_MAPPING.get(gender)
    date_of_birth_value = None
    if date_of_birth:
        date_of_birth_value = str(date_of_birth)

    payload = {
        'phone': phone,
        "first_name": first_name,
        "last_name": last_name,
        "gender": gender_value,
        "date_of_birth": date_of_birth_value,
    }
    if age:
        payload['age'] = age
    if email:
        payload['email'] = email
    response = session.post(url, json=payload)
    if not response.ok:
        logger.warning(f"Invalid response received, {response.status_code}: {response.json()}")
        return None
    response_data = response.json()
    return response_data


def get_profile_reports(
        profile_id: str, subscription_id: str | None, api_key: str
):
    url = METSIGHTS_BASE_URL + f"/external/profiles/{profile_id}/reports/"
    session = Session(api_key)
    response = session.get(url, params={"subscription": subscription_id})
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_metsights_report(report_id: str, api_key: str):
    url = (
            METSIGHTS_BASE_URL
            + f"/external/reports/metsights-precision/{report_id}/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_files_for_report(report_id: str, api_key: str, page: int = 1):
    url = (
            METSIGHTS_BASE_URL
            + f"/external/reports/metsights-precision/{report_id}/files/"
    )

    session = Session(api_key)
    response = session.get(url, params={"page": page, "limit": 50})
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    return response_json, None


def get_profile_records(profile_id: str):
    url = f"{METSIGHTS_BASE_URL}/external/profiles/{profile_id}/records/"
    query_parameters = {"code": "BIOPEAK_HEALTH"}
    session = Session()
    response = session.get(url, params=query_parameters)
    if not response.ok:
        return None
    response_data = response.json()
    return response_data.get('data')


def get_record(record_id: str):
    url = f"{METSIGHTS_BASE_URL}/external/records/{record_id}/"
    session = Session()
    response = session.get(url)
    if not response.ok:
        return None
    response_data = response.json()
    return response_data.get('data')


def get_record_personalised_plan(record_id: str) -> dict | None:
    url = f"{METSIGHTS_BASE_URL}/external/records/{record_id}/personalised-plan/"
    session = Session()
    response = session.get(url)
    if not response.ok:
        return None
    response_data = response.json()
    return response_data.get('data')


def get_record_documents(
        record_id: str, *, category_type=None, module_type=None, file_type=None,
):
    url = f"{METSIGHTS_BASE_URL}/external/records/{record_id}/documents/"
    session = Session()
    query_parameters = {
        "category_type": category_type,
        "module_type": module_type,
        "file_type": file_type,
    }
    response = session.get(url, params=query_parameters)
    if not response.ok:
        return None
    response_data = response.json()
    return response_data.get('data')


def export_record_reports(record_id: str, email: str):
    url = f"{METSIGHTS_BASE_URL}/records/{record_id}/export-reports/"
    session = Session()
    response = session.post(url, json={"email": email})
    if not response.ok:
        return None
    return response.json()


def get_trends_for_report(report_id: str, api_key: str):
    url = (
            METSIGHTS_BASE_URL
            + f"/external/reports/metsights-precision/{report_id}/trends/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_health_risk_landscape_report(report_id: str, api_key: str):
    url = METSIGHTS_BASE_URL + (
        f"/external/reports/metsights-precision/{report_id}/"
        f"health-risk-landscape/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_lifestyle_blueprint_report(report_id: str, api_key: str):
    url = METSIGHTS_BASE_URL + (
        f"/external/reports/metsights-precision/{report_id}/"
        f"lifestyle-blueprint/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_supplement_blueprint_report(report_id: str, api_key: str):
    url = METSIGHTS_BASE_URL + (
        f"/external/reports/metsights-precision/{report_id}/"
        f"supplement-blueprint/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_consolidated_precision_report(report_id: str, api_key: str):
    url = METSIGHTS_BASE_URL + (
        f"/external/reports/metsights-precision/{report_id}/"
        f"consolidated/"
    )

    session = Session(api_key)
    response = session.get(url)
    if not response.ok:
        return None, METSIGHTS_REPORT_UNAVAILABLE
    response_json = response.json()
    data = response_json.get('data')
    return data, None


def get_metsights_report_file(file_url: str) -> tuple[BinaryIO | None, str | None]:
    (downloaded_file, content_type), error = download_external_file(file_url)
    if downloaded_file is None:
        return None, error
    return downloaded_file, None
