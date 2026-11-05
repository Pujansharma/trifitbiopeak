"""Run a scheduled queue drain once across all ECS tasks, using PostgreSQL.

This command supervises an external queue runner; it does not change job
handlers or their lease/claim behavior. Advisory locks are per *database
session*, not per process/container, so overlapping EventBridge RunTask ticks
on separate ECS hosts do not drain the same queue concurrently.
"""

import argparse
import os
import signal
import subprocess
import sys
import time

from django.db import connection
from django.core.management.base import BaseCommand, CommandError


# Stable, separate lock keys for the shared sweep and the long ROOK recovery.
# Separate queues can progress concurrently; each queue has only one drain.
LOCK_KEYS = {
    "shared": 0x42494F5045414B31,  # BIOPEAK1
    "recovery": 0x42494F5045414B32,  # BIOPEAK2
}
RECOVERY_TIMEOUT_SECONDS = 80 * 60  # Shorter than the >=90m DB recovery lease.
LOCK_HEARTBEAT_SECONDS = 10


def stop_process_group(process: subprocess.Popen) -> None:
    """Stop the full child process tree before releasing its database lock."""
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


class Command(BaseCommand):
    help = "Run a scheduled queue entrypoint once across all PostgreSQL-backed ECS tasks."

    def add_arguments(self, parser):
        parser.add_argument("--kind", choices=sorted(LOCK_KEYS), required=True)
        parser.add_argument(
            "--timeout-seconds", type=int, default=0,
            help="Maximum wall-clock runtime; required for recovery, 0 = unbounded for shared.",
        )
        parser.add_argument("command", nargs=argparse.REMAINDER)

    def handle(self, *args, **options):
        kind = options["kind"]
        timeout = options["timeout_seconds"]
        command = list(options["command"])
        if command and command[0] == "--":
            command.pop(0)
        if not command:
            raise CommandError("Provide the command to run after '--'.")
        if kind == "recovery" and not 1 <= timeout <= RECOVERY_TIMEOUT_SECONDS:
            raise CommandError("Recovery must have a timeout between 1 and 4800 seconds.")
        if kind == "shared" and timeout < 0:
            raise CommandError("Shared sweep timeout cannot be negative.")
        if connection.vendor != "postgresql":
            raise CommandError("Singleton queue drains require PostgreSQL advisory locks.")

        lock_key = LOCK_KEYS[kind]
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
            acquired = cursor.fetchone()[0]
        if not acquired:
            self.stdout.write(f"Skipped {kind} sweep: another task already holds its queue lock.")
            return

        # Hold and periodically ping THIS SAME PostgreSQL session while the
        # subprocess runs. Never reconnect after losing its lock: stop the
        # child first to avoid duplicate work in another ECS container.
        lock_session = connection.connection
        process = None
        previous_handlers = {}
        def interrupt_worker(signum, _frame):
            raise CommandError(f"{kind} queue worker interrupted by signal {signum}.")

        try:
            # ECS sends SIGTERM during task replacement. Terminate the entire
            # subprocess group *before* releasing the cross-task lock.
            for signum in (signal.SIGTERM, signal.SIGINT):
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupt_worker)
            env = os.environ.copy()
            if kind == "shared":
                env["BIOPEAK_SWEEP_LOCKED"] = "1"
            process = subprocess.Popen(command, env=env, start_new_session=True)
            deadline = time.monotonic() + timeout if timeout else None
            while True:
                remaining = deadline - time.monotonic() if deadline else None
                if remaining is not None and remaining <= 0:
                    raise CommandError(f"{kind} queue worker exceeded its {timeout}s limit.")
                wait_for = min(LOCK_HEARTBEAT_SECONDS, remaining) if remaining is not None else LOCK_HEARTBEAT_SECONDS
                try:
                    exit_status = process.wait(timeout=wait_for)
                    if exit_status != 0:
                        self.stderr.write(f"{kind} queue worker exited with status {exit_status}.")
                        # Preserve the existing sweep script's highest exit code.
                        sys.exit(exit_status)
                    self.stdout.write(self.style.SUCCESS(f"{kind} queue worker completed."))
                    return
                except subprocess.TimeoutExpired:
                    if connection.connection is not lock_session:
                        raise CommandError(f"{kind} queue worker lost its PostgreSQL lock session.")
                    try:
                        with connection.cursor() as cursor:
                            cursor.execute("SELECT 1")
                            cursor.fetchone()
                    except Exception as error:
                        raise CommandError(f"{kind} queue lock heartbeat failed: {error}") from error
                    if connection.connection is not lock_session:
                        raise CommandError(f"{kind} queue worker lost its PostgreSQL lock session.")
        finally:
            if process is not None:
                stop_process_group(process)
            for signum, previous in previous_handlers.items():
                signal.signal(signum, previous)
            # Closing the dedicated supervisor session releases its advisory
            # lock even if an explicit unlock query would fail after disconnect.
            connection.close()
