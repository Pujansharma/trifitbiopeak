"""Run MetSights actions and save each ResultRequest once on completion."""

import threading
import requests

from django.db import close_old_connections, DatabaseError
from django.utils import timezone

from core.utils.log import logger
from integrations.metsights.utils.db import refresh_metsights_counts, set_request_status
from integrations.metsights.utils.results import handle_metsights_report_fetch
from integrations.metsights.utils.submission import process_metsights_order
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus


def refetch_metsights_report(result_request: ResultRequest, provider_api_data: dict) -> None:
    handle_metsights_report_fetch(result_request, provider_api_data, replace_existing=True)


def _get_metsights_request(request_identifier):
    close_old_connections()
    return ResultRequest.objects.select_related(
        "program_service__program__customer_profile",
        "product__provider__api",
        "created_by",
    ).filter(pk=request_identifier).first()


def _run_metsights_task(result_request, process_request):
    result_request.refresh_from_db()
    if result_request.status in [ResultRequestStatus.RUNNING, ResultRequestStatus.CANCELLED]:
        close_old_connections()
        return
    try:
        result_request.status = ResultRequestStatus.RUNNING
        result_request.attempts_count += 1
        result_request.started_at = timezone.localtime()
        result_request.completed_at = None
        result_request.failure_detail = ""
        result_request.save(update_fields=[
            "status", "attempts_count", "started_at", "completed_at",
            "failure_detail", "updated_at",
        ])
        provider = result_request.product.provider
        provider_api = getattr(provider, "api", None)
        if not (
            result_request.program_service.is_active and result_request.product.is_active
            and provider.is_active and provider.is_api_enabled and provider_api and provider_api.is_active
        ):
            set_request_status(result_request, ResultRequestStatus.FAILED, "MetSights configuration or service is inactive.")
            return
        error = process_request(result_request, provider_api.data or {})
        if error:
            set_request_status(result_request, ResultRequestStatus.FAILED, error)
    except (OSError, DatabaseError, requests.RequestException) as error:
        logger.error(f"MetSights task failed: reason={type(error).__name__}")
        if result_request is not None:
            set_request_status(result_request, ResultRequestStatus.FAILED, "MetSights processing failed.")
    finally:
        try:
            if result_request is not None:

                result_request.completed_at = timezone.localtime()
                ResultRequest.objects.filter(pk=result_request.pk).exclude(
                    status=ResultRequestStatus.CANCELLED,
                ).update(
                    status=result_request.status, data=result_request.data,
                    is_submitted=result_request.is_submitted, completed_at=result_request.completed_at,
                    failure_detail=result_request.failure_detail,
                    updated_at=timezone.localtime(),
                )
                refresh_metsights_counts(result_request)

        finally:
            close_old_connections()


def run_metsights_submission(request_identifier: str) -> None:
    result_request = _get_metsights_request(request_identifier)
    if result_request is None or result_request.status != ResultRequestStatus.QUEUED:
        close_old_connections()
        return
    _run_metsights_task(result_request, process_metsights_order)


def run_metsights_fetch(request_identifier: str) -> None:
    result_request = _get_metsights_request(request_identifier)
    if result_request is None or result_request.status in [
        ResultRequestStatus.QUEUED,
        ResultRequestStatus.RUNNING,
        ResultRequestStatus.CANCELLED,
    ]:
        close_old_connections()
        return
    _run_metsights_task(result_request, handle_metsights_report_fetch)


def run_metsights_refetch(request_identifier: str) -> None:
    result_request = _get_metsights_request(request_identifier)
    if result_request is None or result_request.status != ResultRequestStatus.QUEUED:
        close_old_connections()
        return
    _run_metsights_task(result_request, refetch_metsights_report)


class MetsightsSubmissionThread(threading.Thread):
    def __init__(self, request_identifier: str) -> None:
        self.request_identifier = request_identifier
        threading.Thread.__init__(self)

    def run(self) -> None:
        run_metsights_submission(self.request_identifier)


class MetsightsFetchThread(threading.Thread):
    def __init__(self, request_identifier: str) -> None:
        self.request_identifier = request_identifier
        threading.Thread.__init__(self)

    def run(self) -> None:
        run_metsights_fetch(self.request_identifier)


class MetsightsRefetchThread(threading.Thread):
    def __init__(self, request_identifier: str) -> None:
        self.request_identifier = request_identifier
        threading.Thread.__init__(self)

    def run(self) -> None:
        run_metsights_refetch(self.request_identifier)


def start_metsights_submission_task(result_request: ResultRequest) -> None:
    MetsightsSubmissionThread(str(result_request.pk)).start()


def start_metsights_fetch_task(result_request: ResultRequest) -> None:
    MetsightsFetchThread(str(result_request.pk)).start()


def start_metsights_refetch_task(result_request: ResultRequest) -> None:
    MetsightsRefetchThread(str(result_request.pk)).start()
