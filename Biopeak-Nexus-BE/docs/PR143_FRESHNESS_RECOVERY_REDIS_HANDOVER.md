# Biopeak Nexus PR #143 - Freshness, Recovery, Shared Throttling

## Baseline and scope

Based on `Biopeak-Nexus-BE-PR143-Reconnect-Authorization-Host-Fixed.zip`.
Only the reviewer-identified freshness/backlog, recovery duplication, scheduler
query efficiency, and shared Django throttle cache were changed. No database
models, migrations or unrelated product APIs were touched.

## 1. P1 - Freshness enqueue accumulation

- The scheduler selects only profiles due for an hourly freshness check and
  skips any PENDING, RUNNING or retryable FAILED freshness job for that profile.
- The query is bounded to 25 due profiles per sweep by default; the CLI
  `--freshness-limit` can choose 0-50. It orders the oldest last-checked
  profiles first to avoid starving high-ID profiles under the cap.
- A stable idempotency key `freshness:<profile_pk>` is used. COMPLETED jobs
  (or exhausted FAILED jobs) are requeued by conditional update after the
  hourly interval, resetting the attempt counter and prior run metadata.
- Legacy per-hour rows remain for traceability and drain normally. The new
  scheduler does not create additional per-hour freshness rows, so ongoing
  unbounded hourly growth is stopped. Historical rows should be archived
  according to the team's agreed retention policy; none are deleted here.

## 2. P1 - Recovery duplication after reauthorization

- `authorization_confirmed` uses `enqueue_or_reuse_recovery_job(manual=True)`.
  An open RUNNING/PENDING/retryable FAILED pull is reused and retains the
  original `import_started_at` generation marker.
- A new generation is claimed and a recovery job created only if no open job
  exists. A fresh authorization may deliberately bypass the one-hour automatic
  recovery cooldown.
- The three notification-triggered recovery inserts also reuse the same
  helper; the previous helper already covered Retry Sync and scheduled pulls.

## 3. P2 - Scheduler recovery query efficiency

- `connections_requiring_recovery_pull()` now selects the customer profile
  eagerly, excludes open recovery jobs using `Exists`, and excludes those
  started in the preceding hour. Both conditions are enforced *before* the
  per-connection helper and its atomic compare-and-swap.

## 4. P1 - Multi-ECS rate limiting (reviewer resolution)

- The `health` cache remains `DummyCache`; PostgreSQL snapshots are still the
  cross-worker source of truth for health dashboard data.
- `CACHES['default']` is configured as Django `RedisCache` in staging and
  production when `STG_REDIS_URL` / `PRD_REDIS_URL` is provided.
- When staging/production wearables are enabled, the endpoint becomes
  mandatory and missing config blocks startup (no silent LocMem fallback).
- The `redis` Python package is added to `pyproject.toml` and a pinned
  wheel-backed entry to `uv.lock`. **Run `uv lock` on Python 3.14 in a networked
  environment and commit its verified output** before CI/GA; this sandbox
  cannot fetch the supported Python toolchain or re-resolve dependencies.
- The client must provision ElastiCache Redis, configure credentials/TLS,
  make it reachable from every ECS task, and verify a cache key written by one
  task is visible to another. Keep AWS WAF as a separate edge-level cap.

## Verification before merging

Use Python 3.14 and an isolated PostgreSQL test database:

```bash
uv lock
uv sync --frozen
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test wearables.tests.test_pr143_queue_redis_followup
uv run python manage.py test wearables.tests.test_pr143_followup_fixes
uv run python manage.py test wearables.tests.test_reconnect_authorization_host
uv run python manage.py test wearables.tests
```

In staging with real ElastiCache (redacted secret values):

```bash
uv run python manage.py check --settings=core.settings.staging
uv run python manage.py check_rook_configuration --strict --settings=core.settings.staging
uv run python manage.py shell --settings=core.settings.staging -c "from django.core.cache import cache; cache.set('shared-cache-probe', 'ok', 30); assert cache.get('shared-cache-probe') == 'ok'"
```

Test double scheduler invocation, 300+ active profiles, webhook normalization
under backlog, reconnect during an open recovery, and two independent ECS
workers sharing rate-limit counters. Never test against production patient data.

## Release limitations

Isolated syntax/behavior checks only in this artifact environment. The full
Django + PostgreSQL + Redis + ROOK integration suite has not been executed here.
Redis deployment and clinical/data protection review remain external tasks.
