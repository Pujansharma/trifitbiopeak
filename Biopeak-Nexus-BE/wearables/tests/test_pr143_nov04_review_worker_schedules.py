"""Regression tests for the Nov-04 ROOK recovery scheduling review.

The command tests mock the runner process/database; queue tests use mocks and
need no live ROOK calls. Full release tests still require PostgreSQL.
"""

from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from wearables.management.commands import enqueue_health_freshness_checks as enqueuer
from wearables.management.commands import run_scheduled_worker as runner


class ScheduledWorkerLockTests(SimpleTestCase):
    def _database(self, connection, *, acquired=True):
        connection.vendor = "postgresql"
        connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (acquired,)
        connection.connection = object()

    @patch.object(runner.subprocess, "Popen")
    @patch.object(runner, "connection")
    def test_held_recovery_lock_skips_second_worker(self, connection, popen):
        self._database(connection, acquired=False)
        runner.Command().handle(
            kind="recovery", timeout_seconds=4800,
            command=["--", "python", "manage.py", "process_health_jobs", "--only-recovery"],
        )
        popen.assert_not_called()

    @patch.object(runner.subprocess, "Popen")
    @patch.object(runner, "connection")
    def test_shared_sweep_runs_under_distinct_global_lock(self, connection, popen):
        self._database(connection)
        popen.return_value.wait.return_value = 0
        popen.return_value.poll.return_value = 0
        runner.Command().handle(
            kind="shared", timeout_seconds=0,
            command=["--", "bash", "assets/scripts/sweep_jobs.sh"],
        )
        args, kwargs = popen.call_args
        self.assertEqual(args[0], ["bash", "assets/scripts/sweep_jobs.sh"])
        self.assertEqual(kwargs["env"]["BIOPEAK_SWEEP_LOCKED"], "1")
        self.assertTrue(kwargs["start_new_session"])
        connection.close.assert_called_once()

    @patch.object(runner.subprocess, "Popen")
    @patch.object(runner, "connection")
    def test_recovery_must_have_bounded_runtime(self, connection, popen):
        for seconds in (0, 4801):
            with self.assertRaises(CommandError):
                runner.Command().handle(
                    kind="recovery", timeout_seconds=seconds,
                    command=["--", "python", "manage.py", "process_health_jobs", "--only-recovery"],
                )
        popen.assert_not_called()
        connection.cursor.assert_not_called()

    @patch.object(runner.subprocess, "Popen")
    @patch.object(runner, "connection")
    def test_sqlite_cannot_silently_disable_singleton_guard(self, connection, popen):
        connection.vendor = "sqlite"
        with self.assertRaisesRegex(CommandError, "PostgreSQL"):
            runner.Command().handle(
                kind="recovery", timeout_seconds=4800,
                command=["--", "python", "manage.py", "process_health_jobs", "--only-recovery"],
            )
        popen.assert_not_called()


class RecoveryEnqueueBudgetTests(SimpleTestCase):
    @override_settings(WEARABLES_ENABLED=True)
    def test_recovery_enqueues_oldest_first_with_available_capacity(self):
        connection_a = MagicMock(customer_profile="a")
        connection_b = MagicMock(customer_profile="b")
        ordered = MagicMock()
        ordered.__getitem__.return_value.iterator.return_value = iter([connection_a])
        with (
            patch.object(enqueuer.WearableConnection.objects, "filter") as pending,
            patch.object(enqueuer.CustomerProfile.objects, "filter") as profiles,
            patch.object(enqueuer, "eligible_freshness_profiles") as eligible,
            patch.object(enqueuer.HealthProcessingJob.objects, "filter") as jobs,
            patch.object(enqueuer, "connections_requiring_recovery_pull") as due,
            patch.object(enqueuer, "enqueue_or_reuse_recovery_job", return_value=(object(), True)) as queue,
            patch.object(enqueuer, "enqueue_orphaned_normalization_jobs", return_value={"queued": 0, "requiresOperatorReview": 0}),
        ):
            profiles.return_value.iterator.return_value = iter(())
            eligible.return_value.iterator.return_value = iter(())
            jobs.return_value.filter.return_value.count.return_value = 9
            due.return_value.order_by.return_value = ordered
            enqueuer.Command().handle(freshness_limit=0, recovery_limit=2)
            limit_slice = ordered.__getitem__.call_args.args[0]
            self.assertIsInstance(limit_slice, slice)
            self.assertEqual(limit_slice.stop, 1)  # 10 open global cap minus 9 existing
            self.assertEqual(queue.call_count, 1)
            self.assertEqual(queue.call_args.kwargs["connection"], connection_a)
            due.return_value.order_by.assert_called_once()

    @override_settings(WEARABLES_ENABLED=True)
    def test_full_recovery_queue_adds_no_more_jobs(self):
        with (
            patch.object(enqueuer.WearableConnection.objects, "filter"),
            patch.object(enqueuer.CustomerProfile.objects, "filter") as profiles,
            patch.object(enqueuer, "eligible_freshness_profiles") as eligible,
            patch.object(enqueuer.HealthProcessingJob.objects, "filter") as jobs,
            patch.object(enqueuer, "connections_requiring_recovery_pull") as due,
            patch.object(enqueuer, "enqueue_or_reuse_recovery_job") as queue,
            patch.object(enqueuer, "enqueue_orphaned_normalization_jobs", return_value={"queued": 0, "requiresOperatorReview": 0}),
        ):
            profiles.return_value.iterator.return_value = iter(())
            eligible.return_value.iterator.return_value = iter(())
            jobs.return_value.filter.return_value.count.return_value = 10
            due.return_value.order_by.return_value.__getitem__.return_value.iterator.return_value = iter(())
            enqueuer.Command().handle(freshness_limit=0, recovery_limit=2)
            self.assertEqual(due.return_value.order_by.return_value.__getitem__.call_args.args[0].stop, 0)
            queue.assert_not_called()
