from core.utils.views import BaseCreateAPIView
from webhooks.bugspeaks.tasks import start_bugspeaks_webhook_task


class BugspeaksWebhookView(BaseCreateAPIView):
    def post(self, request, *args, **kwargs):
        start_bugspeaks_webhook_task(request.data)
        return self.send_response("Webhook received successfully", status=202)
