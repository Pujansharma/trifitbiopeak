from uuid import uuid4

from django.test import SimpleTestCase, override_settings

from integrations.communications.whatsapp.dispatch import publish_whatsapp_job_batches
from integrations.utils.constants import WHATSAPP_DISPATCH_BATCH_SIZE
from integrations.utils.sqs_dispatch import (
    chunk_job_ids,
    fifo_message_deduplication_id,
    message_body_for_job_ids,
)
from infra.config import enabled_integrations, load_integrations_config


class WhatsAppDispatchChunkTests(SimpleTestCase):
    def test_chunk_job_ids_never_empty_and_respects_batch_size(self):
        job_ids = [uuid4() for _ in range(56)]
        batches = list(chunk_job_ids(job_ids, batch_size=WHATSAPP_DISPATCH_BATCH_SIZE))
        self.assertEqual(len(batches), 6)
        self.assertEqual(len(batches[0]), 10)
        self.assertEqual(len(batches[-1]), 6)
        self.assertTrue(all(batch for batch in batches))

    def test_chunk_job_ids_dedupes(self):
        job_id = uuid4()
        batches = list(chunk_job_ids([job_id, job_id, job_id], batch_size=10))
        self.assertEqual(batches, [[job_id]])

    def test_message_body_for_job_ids(self):
        job_id = uuid4()
        body = message_body_for_job_ids([job_id])
        self.assertIn(str(job_id), body)
        self.assertIn("job_ids", body)

    def test_fifo_message_deduplication_id_fits_sqs_limit(self):
        job_ids = [uuid4() for _ in range(WHATSAPP_DISPATCH_BATCH_SIZE)]
        dedup_id = fifo_message_deduplication_id(job_ids)
        self.assertEqual(len(dedup_id), 64)
        self.assertLessEqual(len(dedup_id), 128)
        self.assertEqual(dedup_id, fifo_message_deduplication_id(job_ids))

    @override_settings(WHATSAPP_OUTBOX_QUEUE_URL="")
    def test_publish_without_queue_url_returns_empty(self):
        published = publish_whatsapp_job_batches([uuid4()])
        self.assertEqual(published, [])

    def test_integrations_yaml_timeouts_and_launcher(self):
        config = load_integrations_config()
        whatsapp = enabled_integrations(config)["whatsapp"]
        self.assertEqual(whatsapp["queue"]["visibility_timeout_seconds"], 600)
        self.assertEqual(whatsapp["queue"]["message_retention_days"], 1)
        self.assertEqual(whatsapp["dlq"]["retention_days"], 1)
        self.assertEqual(whatsapp["launcher"]["type"], "lambda")
