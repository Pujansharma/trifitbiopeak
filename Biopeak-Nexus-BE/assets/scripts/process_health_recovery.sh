#!/bin/bash
set -euo pipefail

# Separate scheduled ECS task (not part of the 15-minute shared sweep).
# Global PostgreSQL advisory lock prevents overlapping recovery workers even
# when EventBridge fires again before a previous 7-day ROOK pull finishes.
# Limit 1 leaves the rest of the health queue for the shared worker.
exec python manage.py run_scheduled_worker --kind recovery --timeout-seconds 4800 -- \
    python manage.py process_health_jobs --only-recovery --limit 1
