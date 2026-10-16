from core.utils.views import BaseCreateAPIView
from webhooks.strand_genomics.tasks import start_strand_genomics_webhook_task


class StrandGenomicsWebhookView(BaseCreateAPIView):
    def post(self, request, *args, **kwargs):
        start_strand_genomics_webhook_task(request.data)
        return self.send_response("Webhook received successfully", status=202)
