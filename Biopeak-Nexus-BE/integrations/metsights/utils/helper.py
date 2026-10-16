"""One remote operation per helper; callers own iteration and workflow state."""

from datetime import date
from typing import BinaryIO

from integrations.metsights.utils.sdk import (
    GENDER_MAPPING,
    METSIGHTS_BASE_URL,
    METSIGHTS_REQUEST_ERROR,
    Session,
)


def create_profile(api_key: str, gender: str, date_of_birth: date):
    url = f"{METSIGHTS_BASE_URL}/external/profiles/"
    payload = {
        "gender": GENDER_MAPPING[gender],
        "date_of_birth": str(date_of_birth),
    }
    session = Session(api_key)
    response = session.post(url, json=payload)
    response_data = response.json()
    if not response.ok:
        return None, str(response_data.get("detail") or METSIGHTS_REQUEST_ERROR)
    return response_data["data"], None


def create_record(api_key: str, profile_id: str, subscription_id: str):
    url = f"{METSIGHTS_BASE_URL}/external/profiles/{profile_id}/records/"
    payload = {"subscription_id": subscription_id}
    session = Session(api_key)
    response = session.post(url, json=payload)
    response_data = response.json()
    if not response.ok:
        return None, str(response_data.get("detail") or METSIGHTS_REQUEST_ERROR)
    return response_data["data"], None


def create_attachment(
        api_key: str,
        record_id: str,
        module_type: str,
        assessment_date: date,
        data: object | None = None,
):
    url = f"{METSIGHTS_BASE_URL}/external/records/{record_id}/attachments/"
    payload = {
        "module_type": module_type,
        "assessment_date": str(assessment_date),
        "source": "provider",
    }
    if data is not None:
        payload["data"] = data
    session = Session(api_key)
    response = session.post(url, json=payload)
    response_data = response.json()
    if not response.ok:
        return None, str(response_data.get("detail") or METSIGHTS_REQUEST_ERROR)
    return response_data["data"], None


def upload_document(
        api_key: str,
        attachment_id: str,
        uploaded_file: BinaryIO,
        filename: str,
        content_type: str,
        file_type: str | None = None,
        attachment_date: date | None = None,
):
    url = f"{METSIGHTS_BASE_URL}/external/record-attachments/{attachment_id}/documents/"
    payload = {"has_pii": "false"}
    if file_type:
        payload["file_type"] = file_type
    if attachment_date:
        payload["attachment_date"] = str(attachment_date)
    files = {"file": (filename, uploaded_file, content_type)}
    session = Session(api_key)
    with session.post(
            url,
            data=payload,
            files=files,
            timeout=60,
            stream=True,
    ) as response:
        response_data = response.json()
    if not response.ok:
        return None, str(response_data.get("detail") or METSIGHTS_REQUEST_ERROR)
    return response_data["data"], None
