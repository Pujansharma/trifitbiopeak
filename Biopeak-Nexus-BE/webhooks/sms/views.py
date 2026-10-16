from typing import Any

from rest_framework.permissions import AllowAny
from rest_framework.request import Request

from core.utils.views import BaseCreateAPIView
from webhooks.sms.serializers import SMSWebhookSerializer


class SMSWebhookView(BaseCreateAPIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    serializer_class = SMSWebhookSerializer

    def post(self, request: Request, *args: Any, **kwargs: Any):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return self.send_response("Webhook received successfully")
