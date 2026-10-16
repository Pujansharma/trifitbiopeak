import io
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from pathlib import Path
from urllib.parse import urlparse

import requests
from django.core.files.base import ContentFile
from django.utils import timezone
from django.template.loader import get_template

from core.utils.emails import send_templated_email
from webhooks.metsights.models import MetSightsExportHistory

REPORTS_EXPORT_EMAIL_SUBJECT = "Your Reports Are Ready — Biopeak"
REPORTS_EXPORT_EMAIL_TEMPLATE = "mails/metsights_reports_export_email.html"
REQUEST_TIMEOUT_SECONDS = 30
REPORTS_ZIP_SUFFIX_LENGTH = 6


def get_report_file_name(file_payload: dict) -> str:
    file_url = file_payload.get("file_url") or ""
    return Path(urlparse(file_url).path).name


def fetch_report_file(file_payload: dict) -> tuple[str, bytes] | None:
    file_url: str | None = file_payload.get("file_url")
    filename = get_report_file_name(file_payload)
    if not file_url or not filename:
        return None

    try:
        response = requests.get(
            file_url,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        return None

    if not response.ok:
        return None

    return filename, response.content


def fetch_report_files(files: Iterable[dict]) -> Iterator[tuple[str, bytes]]:
    for file_payload in files:
        if isinstance(file_payload, dict) and file_payload.get("file_url"):
            attachment = fetch_report_file(file_payload)
            if attachment:
                yield attachment


def get_unique_zip_names(filenames: Iterable[str]) -> Iterator[str]:
    seen: dict[str, int] = {}
    for filename in filenames:
        count = seen.get(filename, 0)
        seen[filename] = count + 1
        if count == 0:
            yield filename
        else:
            path = Path(filename)
            yield f"{path.stem} ({count}){path.suffix}"


def get_reports_zip_filename() -> str:
    timestamp = timezone.localtime().strftime("%Y%m%d%H%M%S")
    suffix = uuid.uuid7().hex[-REPORTS_ZIP_SUFFIX_LENGTH:]
    return f"exports_{timestamp}_{suffix}.zip"


def build_reports_zip(files: list[tuple[str, bytes]]) -> bytes:
    names = get_unique_zip_names(filename for filename, _ in files)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, (_, content) in zip(names, files):
            archive.writestr(name, content)
    return buffer.getvalue()


def create_reports_export_history(
    email: str, files: list[tuple[str, bytes]]
) -> MetSightsExportHistory:
    export_history = MetSightsExportHistory(email=email)
    export_history.file.save(
        get_reports_zip_filename(),
        ContentFile(build_reports_zip(files)),
        save=False,
    )
    export_history.save()
    return export_history


def get_reports_export_email_template(
    subject: str, first_name: str, download_url: str
) -> str:
    return get_template(REPORTS_EXPORT_EMAIL_TEMPLATE).render(
        {"subject": subject, "first_name": first_name, "download_url": download_url}
    )


def send_reports_export_email(email, first_name, files) -> None:
    if not email:
        return

    available_files = list(fetch_report_files(files))
    if not available_files:
        return

    export_history = create_reports_export_history(email, available_files)
    subject = "Reports export"
    template = get_reports_export_email_template(
        subject, first_name, export_history.file.url
    )
    send_templated_email(
        REPORTS_EXPORT_EMAIL_SUBJECT,
        template,
        email,
        from_email="care@mails.biopeak.com",
    )
