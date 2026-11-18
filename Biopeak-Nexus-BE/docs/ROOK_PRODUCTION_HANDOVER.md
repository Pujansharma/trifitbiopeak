# ROOK parallel recovery and durable wake-up handover

> Current behavior and API additions: [ROOK_PHASE1_IMPROVEMENTS_20261110.md](ROOK_PHASE1_IMPROVEMENTS_20261110.md). The user confirmed the missing or >=7-day-old pull-coverage nightly rule on 10 November 2026. Infrastructure guidance below remains applicable; previous statements that this selection still needs product confirmation are superseded. Current validation is recorded in [ROOK_PHASE1_VALIDATION_20261110.md](ROOK_PHASE1_VALIDATION_20261110.md).

**Status:** implementation candidate for staging acceptance; not production-certified.
**Baseline:** `Biopeak_ROOK_Manager_Diagram_Flows_Updated.zip` from this conversation.
**Scope:** ROOK only. No appointment, WhatsApp, customer, therapy, AI, supplementation,
shared sweep, dependency lock, route mount or existing deployment workflow is changed.
This is not a merge against an unseen newer client branch.

## 1. Execution design

PostgreSQL `RookOutbox` remains the authoritative work queue. Dedicated ROOK
SQS queues contain wake-up hints only. A wake acknowledgement is NOT health-job
completion. The WhatsApp design pattern is reused; its queue, code, and consumer are not.

1. Connect still obtains the interactive authorization URL synchronously. The user
   authorizes the provider; queued server-side verification gates initial history.
2. Initial import, manual sync and midnight discovery use the same recovery pipeline.
3. Manual admission is serialized per connection. An accepted request within six
   elapsed hours of the previous accepted MANUAL request is an informational no-op.
4. The job/target and wake intent are saved durably. A short best-effort SQS send runs
   after commit. Failure retains unsent intent; DB polling/reconciliation rediscovers work.
5. One dedicated health consumer and up to five recovery consumers drain ROOK work.
   The pool has five named DB slots across the deployment, not five per container.
6. A connection can own only one RUNNING recovery. Conditional claims, a partial
   unique constraint, authorization generation and attempt tokens protect takeover.
7. Recovery fetches bounded date/category slices (default three requests), normalizes,
   checkpoints, and refreshes partial analytics when new documents were processed.
8. Full coverage advances only when every unit in the frozen plan has been visited.
   Provider no-data responses are not fabricated zero observations. A covered pull
   window is NOT a guarantee that the provider will never deliver a later correction.
9. A newer accepted target while work is active is retained separately and becomes a
   follow-up plan on the SAME job after the frozen plan finishes. Finalization and
   request admission serialize on the connection, avoiding a lost-target race.
10. Webhooks continue through normalization/analytics independently. Native sources
    still require the mobile SDK and on-device permissions; server pulls are API-source only.

The old 15-minute recovery timer is replaced with a continuous service. The midnight
scheduler and a five-minute bounded reconciliation timer remain. SQS is optional for
correctness: missing queue URLs fall back to database polling, but production should
configure the dedicated queues for the agreed pattern.

## 2. Explicit policy decisions

- Six hours means elapsed time since the last ACCEPTED manual request for that
  connection, not last successful pull, app login, or last webhook. Requests inside
  the interval do not move its end. Initial imports, scheduled work and system retry
  do not spend the manual cooldown. This adopts the proposed policy from discussion;
  it is not inferred from an ambiguous diagram timestamp.
- Five is an initial global upper bound, not a capacity benchmark. Settings above
  five are rejected. Rollout may use fewer ECS tasks. All overlapping revisions must
  use compatible coordination and quota settings. Do not run old worker binaries.
- Nightly defaults to `stale`: `synced_through` absent or at least seven days old,
  in Asia/Kolkata. `rolling` rechecks seven dates. This remains a documented assumption
  requiring product confirmation; it is not based on app inactivity.
- Event instants remain timezone-aware; database UTC behavior is retained. Local
  health dates use the member timezone. Cooldown and quota clocks use UTC instants.
  Existing ingestion behavior for naive upstream timestamps is not silently rewritten.
- Initial history is still controlled by existing settings/entitlements. Production
  baseline disables pre-existing history. Do not promise seven-day history until approved.

## 3. Safety and retry behavior

A supervisor owns an execution slot for a maximum 780 seconds, with bounded shutdown
and lease grace. The long-lived consumer starts new bounded attempts; it is not itself
limited to 13 minutes. Reaching a normal slice boundary, waiting for provider budget,
or awaiting authorization/revocation is a continuation and does not consume failure
attempts. Genuine errors use bounded exponential backoff with jitter; exhausted jobs
remain visible for operator review. The supervisor records owned failures before
requesting termination when the DB is reachable. SIGKILL/database loss cannot execute
cleanup; deadline/lease recovery and stale-write fencing remain necessary.

ORM UPDATEs serialize short local state transitions. No provider HTTP is performed
while holding these coordination transactions. No raw SQL or `select_for_update()`
was introduced. Existing ROOK uses of that forbidden API were replaced, not simply
removed. Separate identity rows coordinate profile writes without modifying customer
rows. Old tokens cannot finalize newer attempts. A late/zombie process cannot be
promised physically absent during all failures; persisted effects are fenced.

Local disconnect/revocation stays immediate, remote revoke is queued. Health consumers
can drain REVOKE_CONNECTION even when the rollout feature is off. Reconnect remains
blocked while remote revocation is pending. `ROOK_PULLS_PAUSED=true` stops new recovery
selection; it does not stop webhook processing or consent cleanup.

The ROOK HTTP client reserves a shared DB-backed account budget before ALL its API
calls, including API-server authorizer requests. HTTP 429 Retry-After updates a shared
backoff. Quota deferral does not spend failure attempts. GET verification progress is
checkpointed before the revoke POST so a tight budget does not endlessly repeat GET.

**Quota configuration is mandatory.** No subscription limits are assumed. Per-minute
admission is smoothed; the additional daily counter resets at UTC midnight. Allocate a
budget inside the contracted limit, including external clients using these credentials.
If the contract has rolling-day/per-provider limits, align the allocation conservatively
and validate with ROOK before enabling; this is not a universal provider quota emulator.

## 4. API compatibility

Paths, request bodies, authentication and `{detail, data}` envelopes are preserved.
New serialized connection fields are additive: `lastManualSyncQueuedAt`,
`pendingSyncRequestedAt`, `lastDataProcessedAt`.

`POST /api/v1/devices/sync/`:
- HTTP 202: accepted; `queued=true`, `alreadyQueued`, `jobId`, `connection` and additive
  `syncRequestAccepted=true`, `cooldownActive=false`, `nextSyncAllowedAt`.
- HTTP 200 inside cooldown: `queued=false`, `syncRequestAccepted=false`,
  `cooldownActive=true`, next allowed time and existing job ID when active.
- Neither response means the historical import is complete. Frontend should display
  existing data plus import status, not an empty screen until completion.
- Connect may return HTTP 429 with Retry-After when the approved shared budget is busy.

Bruno `POST Retry Sync.bru` documents the changed behavior using inherited auth and
existing environment variables. No production tokens or health payloads are embedded.

## 5. Schema and migration gate - OWNER ACTION REQUIRED

Repository rules assign migrations to its owner. No migration files are created,
rewritten or deleted by this package. The earlier manager package already had unapplied
model additions; the owner must generate a migration against the ACTUAL branch.

Schema that must exist (wearables migrations through `0005`):
- WearableConnection: last_manual_sync_queued_at, pending_sync_requested_at,
  last_data_processed_at, authorization generations, sync timestamps.
- RookOutbox (renamed from HealthProcessingJob): claim_token, locked_at,
  wake_version / wake_sent_version / wake_next_attempt_at,
  `uniq_rook_running_fetch`. No `deadline_at`, no `worker_run_id`, no
  `RookWorkerLease` (deleted in `0005`).
- RookRequestBudget: account scope, optimistic revision, next permit, shared backoff,
  UTC date and request counter.

Before adding the unique constraint, stop old consumers and inspect duplicate RUNNING
recoveries using an owner-reviewed ORM diagnostic. Do not delete records or fake
migration history. Back up the DB, review the migration plan, test upgrade on a staging
copy and commit the reviewed migration. An existing applied customer migration must
not be edited to repair another branch.

```bash
uv sync --frozen
# Owner only, in development/staging; review and commit the resulting migration.
uv run python manage.py makemigrations wearables
uv run python manage.py migrate --plan
uv run python manage.py migrate
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run python manage.py check_rook_release
uv run python manage.py test wearables.tests --verbosity 2
```

Production applies committed, reviewed migrations in ONE controlled deployment step.
Do not run migrations in every worker's startup. `check_rook_release` is read-only;
it checks essential schema/configuration and duplicate/legacy workers, but does not
certify the physical constraint, provider, AWS or load performance.

## 6. Dedicated AWS setup

All templates default disabled or desired count zero. Nothing has been provisioned.
Templates are JSON-form YAML, intentionally `.yml` because the repository ignores
`*.json`. JSON generated from private ECS settings remains untracked/private.

1. Provision ROOK via `infra/integrations.yaml` BackgroundJobsStack (same path as
   WA/GC/AI): `rook_auth`, `rook_data_fetch`, scheduled `rook_sync_scan` at midnight
   Asia/Kolkata. Do **not** deploy legacy `assets/infrastructure/rook-*.yml` or
   `build_rook_task_definitions.py` (removed).
2. Inject `ROOK_AUTH_OUTBOX_QUEUE_URL` / `ROOK_DATA_FETCH_OUTBOX_QUEUE_URL` into ECS
   (GHA `export_outbox_queue_env` / SSM). Attach SQS send/delete on the API task role.
3. Configure the SAME approved rate budgets on API and worker tasks. Preserve client
   credentials/feature configuration; do not enable unprovisioned sources.
4. Stop any old always-on ROOK consumers/schedules; wait for in-flight work. Next
   outbox worker wake reclaims stale `RUNNING` rows. Validate via SQS wakes.

Infrastructure checks in this package are offline structure/SDK-shape checks, not AWS
deployment validation. Platform team must validate roles, quotas, image architecture
and private subnet egress in staging.

## 7. Local/staging worker commands

Prod ECS uses Lambda/Chronos → `python manage.py <command>` (no `assets/scripts`
worker shells). Local drain when queue URLs are empty:

```bash
uv run python manage.py process_rook_auth_jobs --limit 50
uv run python manage.py process_rook_data_fetch_jobs --limit 10
uv run python manage.py process_pending_rook_sync_scan
uv run python manage.py rook_queue_status
uv run python manage.py check_rook_release
```

Workers claim `RookOutbox` rows; SQS only wakes RunTask. Wake publish is after commit.

## 8. Operations, testing and rollback

Use `rook_queue_status` for DB state counts, oldest pending age, exhausted failures,
and owned recovery slots. Alert on old eligible work, exhausted recoveries/revokes,
expired attempts, repeated provider 429s, DB failures and missing consumer heartbeats.
SQS backlog alone is not business-job backlog. No health payloads or secrets should
be copied into logs, alerts or Slack. Provider calls log status, not member URLs.

Measure first usable dashboard data separately from complete history. Neither five
workers nor queue admission guarantees a completion time. Provider availability,
quota, payload volume and analytics remain constraints. No 100,000-user claim is made.

Acceptance must include ten simultaneous connections; six-hour races/boundary; lost
and duplicate wakes; duplicate/corrected documents; SIGTERM/SIGKILL and DB outage;
revocation during recovery; stale-owner writes; newer manual target during completion;
provider backoff; midnight eligibility; and native SDK device behavior. Run real
PostgreSQL tests with separate connections, then live ROOK sandbox and ECS staging.

Rollback: stop recovery consumers and disable new schedules, preserve DB data and
additive columns, review/finish expired attempts, then deploy the last verified image
and its matching coordination configuration. Never run incompatible old/new recovery
consumers together. Keep local consent/revocation cleanup available. Do not reverse a
schema migration blindly while newer rows exist.

## 9. Validation status and remaining decisions

See `docs/ROOK_PRODUCTION_VALIDATION.md` for exact executed checks and unexecuted gates.
The default nightly stale interpretation, history entitlement/retention behavior and
naive provider datetime assumptions still require client/provider acceptance. Shared
health caching remains the existing configuration; no new Redis cache/100K design is
silently deployed. This work does not repair unrelated defects in a newer client branch.

Primary reference guidance consulted for this change:
- https://docs.djangoproject.com/en/6.0/topics/db/transactions/
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-short-and-long-polling.html
- https://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/sqs-visibility-timeout.html
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_definition_parameters.html
