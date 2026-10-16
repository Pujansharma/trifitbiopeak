import arrow

from core.utils.log import logger
from integrations.orange_labs.utils.sdk import fetch_order, get_pdf_report


def parse_orange_order_timestamp(timestamp: str | None):
    """Parse an OrangeHealth timestamp, leaving missing or invalid values empty."""
    if not isinstance(timestamp, str) or not timestamp.strip():
        return None
    try:
        return arrow.get(timestamp.strip()).datetime
    except ValueError:
        return None


def get_orange_result_dates(orders: list[dict]):
    """Use the most recently completed order for both stored result dates."""
    latest_order = {}
    latest_completed_timestamp = None
    for order in orders:
        completed_timestamp = parse_orange_order_timestamp(
            order.get("order_completed_at")
        )
        if completed_timestamp is not None and (
                latest_completed_timestamp is None
                or completed_timestamp > latest_completed_timestamp
        ):
            latest_order = order
            latest_completed_timestamp = completed_timestamp

    created_timestamp = parse_orange_order_timestamp(
        latest_order.get("order_created_at")
    )
    return {
        "report_generation_date": (
            latest_completed_timestamp.date()
            if latest_completed_timestamp is not None else None
        ),
        "sample_collection_date": (
            created_timestamp.date() if created_timestamp is not None else None
        ),
    }


def _validate_orange_report_orders(orders: list):
    for order in orders:
        if not isinstance(order, dict):
            return "OrangeHealth returned an invalid order"

        report_file_name = order.get("report_file_name")
        if not isinstance(report_file_name, str) or not report_file_name.strip():
            return "OrangeHealth did not provide a report file name"

        report_url = order.get("report_url")
        if not isinstance(report_url, str) or not report_url.strip():
            return "OrangeHealth did not provide a report URL"

    return None


def process_orange_report_fetch(api_key: str, phone: str):
    """Fetch complete order metadata and every PDF before persistence.

    Report files follow the same order as metadata["orders"]. Any expected
    provider or download failure returns an empty file tuple and an error.
    """
    empty_files = ()
    logger.info("OrangeHealth report fetch started")

    payload, error = fetch_order(api_key=api_key, phone=phone)
    if error:
        logger.error(f"OrangeHealth report fetch failed: error={error}")
        return None, empty_files, error

    if not isinstance(payload, dict):
        error_message = "OrangeHealth returned an invalid report response"
        logger.error(error_message)
        return None, empty_files, error_message

    metadata = payload.get("data")
    if not isinstance(metadata, dict):
        error_message = "OrangeHealth returned invalid report data"
        logger.error(error_message)
        return None, empty_files, error_message

    orders = metadata.get("orders")
    if not isinstance(orders, list):
        error_message = "OrangeHealth returned an invalid orders array"
        logger.error(error_message)
        return metadata, empty_files, error_message

    if not orders:
        error_message = "OrangeHealth returned no report orders"
        logger.warning(error_message)
        return metadata, empty_files, error_message

    error = _validate_orange_report_orders(orders)
    if error:
        logger.warning(f"OrangeHealth report fetch skipped: error={error}")
        return metadata, empty_files, error

    result_files = []
    for order in orders:
        pdf_report, error = get_pdf_report(report_url=order["report_url"])
        if error:
            logger.error(f"OrangeHealth report download failed: error={error}")
            return metadata, empty_files, error
        result_files.append(pdf_report)

    logger.info(
        f"OrangeHealth report fetch completed: reports_count={len(result_files)}"
    )
    return metadata, tuple(result_files), None
