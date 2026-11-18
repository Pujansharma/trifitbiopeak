# ROOK manager flows (current)

Status: **current** as of 2026-11-16. Outbox + SQS→Lambda→ECS (same shape as WA/GC/AI). Older lease-supervisor / always-on consumer docs are obsolete.

Product flows below match the manager diagrams (authorize, Sync, midnight, revoke). Execution is `RookOutbox` + two wake queues + one Chronos midnight scan. No `RookWorkerLease`, no `deadline_at`, no `BIOPEAK_SWEEP_LOCKED`, no `reconcile_rook_jobs`, no legacy `rook-*.yml` CFN.

## Entrypoints (`infra/integrations.yaml`)

| Task | Command | Trigger |
| --- | --- | --- |
| Auth outbox | `process_rook_auth_jobs` | SQS `rook-auth-outbox-jobs` → Lambda → ECS RunTask |
| Data fetch outbox | `process_rook_data_fetch_jobs` | SQS `rook-data-fetch-outbox-jobs` → Lambda → ECS RunTask |
| Midnight discovery | `process_pending_rook_sync_scan` | Chronos `cron(0 0 * * ? *)` Asia/Kolkata |

Env queue URLs (GHA/`export_outbox_queue_env`, not hand-kept in prod `.env`):

- `ROOK_AUTH_OUTBOX_QUEUE_URL`
- `ROOK_DATA_FETCH_OUTBOX_QUEUE_URL`

Local drain: same commands with `--limit` when queue URLs are empty.

## Job types and attempts

| Type | Queue | Attempts |
| --- | --- | --- |
| `authorise_rook_connection` | auth | try 1 / retry 0 |
| `revoke_rook_connection` | auth | try 1 / retry 0 |
| `fetch_rook_data` | data_fetch | try 1 / retry 1 |

Midnight is **not** a job type. Scan enqueues fetch work for stale connections.

Exhausted / terminal fail → user Sync or Reconnect. Defer (slice / rate / auth wait) bumps `wake_version` and schedules an SQS wake. Non-exhausted fail and stale reclaim also schedule a wake when retry budget remains.

## Ownership and reclaim

- Claim: conditional ORM update + `claim_token` + `locked_at` heartbeat.
- Soft slice stop inside one claim: ~780s (code constant; **not** a DB `deadline_at` column).
- Stale `RUNNING` reclaim: on each outbox worker start (`reset_stale_health_jobs`, 15 minutes). No separate reconcile cron.

## Source-to-code mapping

| Manager flow | Implementation |
| --- | --- |
| User authorizes → direct ROOK verification → seven-day initial sync | Connect returns authorization URL. Mobile return bridge and authenticated status refresh call ROOK's authorized-source list directly. If the grant is confirmed, Biopeak authorizes locally and enqueues only the initial data pull. Missing propagation or transient ROOK failures fall back to the per-generation auth outbox. Positive notification hints still use the auth outbox. |
| Sync → current minus last-sync → normalize → analytics | `retry-sync` freezes incremental window, coalesces open work, 202. Recovery resumes by date/pillar; analytics + success timestamps after full window. |
| Midnight → seven-day rule → same pipeline | `process_pending_rook_sync_scan` finds eligible API connections and enqueues the same fetch path. No downloads in the scan command. |
| Revoke → revoke queue | Local consent/connection closes immediately. Durable revoke job confirms source absent upstream. |

### Decisions

| Topic | Current rule |
| --- | --- |
| Nightly eligibility | Hardcoded `stale`: missing or ≥7-day-old `synced_through`. No `ROOK_NIGHTLY_*` env. |
| Midnight timezone | Django `TIME_ZONE` (`Asia/Kolkata`). AWS schedule timezone must match. |
| Failed jobs | Auth/revoke: one try. Fetch: one retry. Defer does not spend failure budget. Exhausted → user re-request. |
| Initial history | Up to seven local dates; respect consent, entitlement, `historical_days_requested`, `ROOK_PREEXISTING_ENABLED`. |

## Authorization and initial import

`POST /api/v1/devices/connect/` still returns an interactive provider URL when needed. The secure callback and authenticated `GET /api/v1/devices/providers/?refresh=true` path now verify the pending grant synchronously through ROOK's authorized-source endpoint. A confirmed source transitions locally and enqueues `fetch_rook_data`; the authorization outbox is fallback-only for propagation delay or transient ROOK failures. Signed positive notification hints remain queue-backed because they are not interactive proof. Generations fence delayed workers/callbacks. Native SDK sources are on-device only; these queues cover API sources.

## Manual Sync

`POST /api/v1/devices/sync/` → 202 with `jobId` / coalesce. Window frozen at enqueue. Worker fetches physical/sleep/body per date, checkpoints, then analytics. Cap units per run via `ROOK_SYNC_UNITS_PER_RUN`; overflow defers with wake.

Timestamps: `last_sync_requested_at` = queued; `synced_through` = processed window upper bound; `last_pull_completed_at` / `last_successful_sync` = completion — not raw webhook receipt.

## Revocation

Disconnect closes local state, bumps generation, cancels open auth/pull jobs, queues revoke. Late notifications do not clear `revoke_pending` until remote confirm. Global consent revoke blocks normalize even if ROOK still delivers briefly.

## Module map

| Module | Role |
| --- | --- |
| `job_processor.py` | Claim + dispatch + wake after defer/retryable fail |
| `job_claims.py` | Claim / complete / defer / fail / stale reclaim |
| `job_queue.py` | Admit rows + `schedule_job_wake` |
| `wake.py` | Eligible publish to auth / data_fetch SQS |
| `authorization_jobs.py` | Auth + revoke handlers |
| `recovery.py` | Fetch / normalize / checkpoint |
| `scheduling.py` / `job_selection.py` | Midnight scan + orphan repair selection |
| `sync_plan.py` | Window math |

No `worker_leases.py` / `worker_shutdown.py` / `process_health_jobs` / `run_scheduled_worker`.

## Schema notes

Wearables `0005`: `RenameModel` HealthProcessingJob → `RookOutbox`; drop midnight job type; `uniq_rook_running_fetch`; remove `deadline_at` / `worker_run_id`; `DeleteModel` `RookWorkerLease`. Owner owns migrations unless explicitly asked to generate.

## Staging checklist (short)

- Authorize API source → direct confirmation when ROOK is ready; otherwise one auth fallback job → one initial fetch.
- Complete seven-date import; check observations + sync timestamps.
- Hammer Sync; one open job; frozen window.
- Kill mid-fetch; next worker reclaim + resume within attempt caps.
- Midnight scan twice same date: idempotent, Asia/Kolkata.
- Revoke during pull: local closed; reconnect blocked until revoke confirms.
- Run `uv run python manage.py test wearables.tests --verbosity 2` on PostgreSQL.

See also: `docs/ROOK_PRODUCTION_HANDOVER.md`, `docs/ENVIRONMENT.md` (ROOK section), `docs/MEMORY.md`.
