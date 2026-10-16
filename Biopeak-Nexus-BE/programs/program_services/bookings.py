"""Run provider booking callbacks and report retrieval."""

import threading

import requests
from django.db import DatabaseError, close_old_connections
from django.utils import timezone

from core.utils.log import logger
from integrations.metsights.tasks import start_metsights_fetch_task
from products.utils.constants import ProviderCallbackFunction
from programs.composites.utils.db import (
    update_composite_program_document_counts,
    update_composite_program_results_count,
)
from programs.program_services.utils.db import (
    update_program_service_document_counts,
    update_program_service_fetch_counts,
    update_program_service_results_count,
    update_result_documents_count,
)
from programs.program_services.utils.order_results import fetch_order_reports
from programs.services.models import ResultRequest
from programs.services.utils.constants import ResultRequestStatus


def process_provider_order(
        result_request: ResultRequest,
        process_request,
        request=None,
):
    request_identifier = result_request.pk
    try:
        result_request.status = ResultRequestStatus.RUNNING
        result_request.attempts_count += 1
        result_request.started_at = timezone.localtime()
        result_request.completed_at = None
        result_request.failure_detail = ""
        result_request.save(update_fields=[
            "status",
            "attempts_count",
            "started_at",
            "completed_at",
            "failure_detail",
            "updated_at",
        ])
        if not process_request:
            result_request.status = ResultRequestStatus.FAILED
            result_request.failure_detail = "Ordering is not supported for this product."
            return
        if not getattr(result_request.product.provider, "api", None):
            result_request.status = ResultRequestStatus.FAILED
            result_request.failure_detail = "Provider API configuration is missing."
            return
        outcome = (
            process_request(result_request, request=request) if request is not None else process_request(result_request)
        )
        success, error = outcome or (None, result_request.failure_detail or "Booking worker could not proceed.")
        if error:
            result_request.status = ResultRequestStatus.FAILED
            result_request.failure_detail = error
    except (requests.RequestException, OSError, DatabaseError, ValueError) as error:
        result_request.status = ResultRequestStatus.FAILED
        result_request.failure_detail = str(error)
    finally:
        if result_request.status == ResultRequestStatus.FAILED:
            logger.error(f"Provider order failed: request={request_identifier} reason={result_request.failure_detail}")
        ResultRequest.objects.filter(
            pk=request_identifier,
            status=ResultRequestStatus.RUNNING
        ).update(
            status=result_request.status,
            failure_detail=result_request.failure_detail,
            completed_at=timezone.localtime(),
            updated_at=timezone.localtime(),
        )
        for result_identifier in result_request.results.values_list("pk", flat=True).iterator():
            update_result_documents_count(result_identifier)
        program_service = result_request.program_service
        update_program_service_results_count(program_service.pk)
        update_program_service_document_counts(program_service.pk)
        update_program_service_fetch_counts(program_service.pk)
        update_composite_program_results_count(program_service.program.pk)
        update_composite_program_document_counts(program_service.program.pk)


def run_provider_submission(result_request, submit_booking, request=None):
    close_old_connections()
    try:
        result_request.refresh_from_db()
        if result_request.product.provider.callback == ProviderCallbackFunction.METFLUX and result_request.is_submitted:
            logger.info(f"Provider submission skipped: request={result_request.pk} reason=already_submitted")
            return
        if result_request.status != ResultRequestStatus.QUEUED:
            logger.info(
                f"Provider submission skipped: request={result_request.pk} status={result_request.status}"
            )
            return
        logger.info(
            f"Provider submission started: request={result_request.pk} "
            f"provider={result_request.product.provider.callback} product={result_request.product.callback}"
        )
        process_provider_order(result_request, submit_booking, request=request)
        logger.info(
            f"Provider submission finished: request={result_request.pk} "
            f"status={result_request.status} is_submitted={result_request.is_submitted}"
        )
    finally:
        close_old_connections()


def run_provider_fetch(result_request):
    close_old_connections()
    try:
        if result_request.status == ResultRequestStatus.CANCELLED:
            return
        process_provider_order(result_request, fetch_order_reports)
    finally:
        close_old_connections()


class ProviderSubmissionThread(threading.Thread):
    def __init__(self, result_request, submit_booking, request=None):
        super().__init__()
        self.result_request = result_request
        self.submit_booking = submit_booking
        self.request = request

    def run(self):
        run_provider_submission(self.result_request, self.submit_booking, request=self.request)


class ProviderFetchThread(threading.Thread):
    def __init__(self, result_request):
        super().__init__()
        self.result_request = result_request

    def run(self):
        run_provider_fetch(self.result_request)


def start_provider_submission_thread(result_request, submit_booking, request=None):
    ProviderSubmissionThread(result_request, submit_booking, request=request).start()


def start_provider_fetch_task(result_request):
    fetch_starters = {ProviderCallbackFunction.METFLUX: start_metsights_fetch_task}
    fetch_starter = fetch_starters.get(result_request.product.provider.callback)
    if fetch_starter:
        fetch_starter(result_request)
        return
    ProviderFetchThread(result_request).start()
