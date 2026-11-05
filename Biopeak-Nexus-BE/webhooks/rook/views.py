from django.conf import settings
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import APIException, NotFound
from rest_framework.permissions import AllowAny

from core.utils.views.main import BaseGenericAPIView
from wearables.services.ingestion import RookIngestionStateChanged, ingest_rook_document
from wearables.services.notifications import process_rook_notification
from wearables.services.signature import verify_rook_webhook_signature


def webhook_documents(payload) -> list[dict]:
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list) and all(isinstance(item, dict) for item in payload):
        return payload
    raise ValueError("ROOK webhook payload must be an object or object array.")


class RookWebhookRetryRequired(APIException):
    status_code = 503
    default_detail = "ROOK ingestion could not be committed; retry the webhook delivery."
    default_code = "rook_ingestion_retry_required"


class RookWebhookView(BaseGenericAPIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def validate_signature(self, payload, request) -> bool:
        if not getattr(settings, "WEARABLES_ENABLED", False):
            raise NotFound("Wearable integration is not enabled.")
        expected_client = getattr(settings, "ROOK_CLIENT_UUID", "")
        valid_clients = {client for client in (
            expected_client, getattr(settings, "ROOK_SDK_CLIENT_UUID", ""),
        ) if client}
        if valid_clients and isinstance(payload, dict) and payload.get("client_uuid") not in valid_clients:
            self.raise_permission_denied("ROOK webhook client UUID does not match this deployment.")
        signature_header = request.headers.get("X-ROOK-HASH", "")
        signature_valid = verify_rook_webhook_signature(
            payload=payload,
            signature_header=signature_header,
        )
        if not signature_valid:
            self.raise_permission_denied("Invalid ROOK webhook signature.")
        return bool(getattr(settings, "ROOK_WEBHOOK_HASH_KEY", ""))


class RookDataWebhookView(RookWebhookView):
    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={202: OpenApiTypes.OBJECT},
    )
    def post(self, request, *args, **kwargs):
        payload = request.data
        if isinstance(payload, list) and getattr(
            settings, "ROOK_WEBHOOK_HASH_KEY", ""
        ):
            self.raise_bad_request(
                "Signed ROOK v2 data webhooks must contain one document."
            )
        signature_valid = self.validate_signature(payload, request)
        try:
            documents = webhook_documents(payload)
            results = [
                ingest_rook_document(document, signature_valid=signature_valid)
                for document in documents
            ]
        except (TypeError, ValueError) as error:
            self.raise_bad_request(str(error))
        except RookIngestionStateChanged as error:
            # The ingestion transaction already rolled back. An explicit 503
            # requests provider retry instead of permanently acknowledging a
            # dropped document with the normal 202 Accepted response.
            raise RookWebhookRetryRequired() from error
        return self.send_response(
            "ROOK webhook accepted.",
            {"results": results},
            status=202,
        )


class RookNotificationWebhookView(RookWebhookView):
    @extend_schema(
        request=OpenApiTypes.OBJECT,
        responses={202: OpenApiTypes.OBJECT},
    )
    def post(self, request, *args, **kwargs):
        payload = request.data
        if not isinstance(payload, dict):
            self.raise_bad_request("ROOK notification must be an object.")
        signature_valid = self.validate_signature(payload, request)
        return self.send_response(
            "ROOK notification accepted.",
            process_rook_notification(payload, signature_valid=signature_valid),
            status=202,
        )

