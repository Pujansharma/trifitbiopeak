"""Offline artifact contracts; not a substitute for AWS deployment validation."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


class InfrastructureContractTests(unittest.TestCase):
    def test_legacy_cloudformation_templates_removed(self):
        infrastructure = ROOT / "assets" / "infrastructure"
        for name in (
            "rook-schedules.yml",
            "rook-worker-services.yml",
            "rook-wake-queues.yml",
        ):
            self.assertFalse((infrastructure / name).exists(), name)
        self.assertFalse((ROOT / "assets/scripts/build_rook_task_definitions.py").exists())
        for name in (
            "process_pending_rook_sync_scan.sh",
            "process_rook_auth_jobs.sh",
            "process_rook_data_fetch_jobs.sh",
        ):
            self.assertFalse((ROOT / "assets/scripts" / name).exists(), name)

    def test_integrations_yaml_has_rook_workers_and_midnight_scan(self):
        text = (ROOT / "infra" / "integrations.yaml").read_text()
        self.assertIn("rook_auth:", text)
        self.assertIn("rook_data_fetch:", text)
        self.assertIn("process_rook_auth_jobs", text)
        self.assertIn("process_rook_data_fetch_jobs", text)
        self.assertIn("ROOK_AUTH_OUTBOX_QUEUE_URL", text)
        self.assertIn("ROOK_DATA_FETCH_OUTBOX_QUEUE_URL", text)
        self.assertIn("rook_sync_scan:", text)
        self.assertIn("process_pending_rook_sync_scan", text)
        self.assertIn("cron(0 0 * * ? *)", text)


if __name__ == "__main__":
    unittest.main()
