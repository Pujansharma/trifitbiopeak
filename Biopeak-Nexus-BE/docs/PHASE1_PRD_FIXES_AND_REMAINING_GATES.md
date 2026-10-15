# Biopeak Phase 1 — Final PRD Fixes and Remaining Release Gates

**Source:** User-supplied *Biopeak Longitudinal Health Platform — PRD (1).html*, draft v1.0, and the prior codebase audit. This report describes what is verifiable **in the Django backend source** and does **not** assert production acceptance. The original client code comparison uses `Biopeak-Nexus-BE(3).zip`, not the live GitHub `main` branch.

## Previously identified code gaps addressed in this revision

| PRD requirement or audit gap | Revised source | Implemented behavior / verification |
|---|---|---|
| 7-/30-day trend detail inconsistency | `wearables/services/analytics.py`, `tests/test_analytics.py` | Domain `card.graph.points`, `card.currentValue`, and `metrics` use selected `days`; default dashboard remains 90 days; baseline computations may use older historical series and are labeled separately |
| History availability incorrectly based on old summaries | `wearables/services/analytics.py` | Uses distinct observed local days within each calendar window; old data alone never enables recent 7d/30d availability |
| Per-reading time flattened to parent document time | `wearables/services/metrics.py`, `ingestion.py`, metric/persistence tests | Extracts measurement timestamps from nested event records and converts to UTC/local date; missing precise instants do not fabricate a new clock time |
| Corrected readings can leave old-day summaries | `wearables/services/ingestion.py`, correction tests | Rebuilds both superseded and newly affected local-day/domain materializations; 200-item observation insert batches |
| Historical source-change checks performed one DB query per measurement | `wearables/services/ingestion.py` | Query for first changed observation per unique canonical metric rather than per each of potentially thousands of heart-rate events; confirm real Aiven/Postgres throughput on staging |
| One denied provider masks a healthy domain card | `wearables/services/analytics.py`, analytics regression tests | Provider errors/permissions scoped to applicable domain with usable data priority; upstream capability data must still be validated |
| Cache stale across independent Render web/cron processes | `wearables/services/analytics.py`, `ingestion.py` | Django process-local health cache keyed with database-backed latest document, connection and identity revision timestamps; accepted corrections schedule invalidation. Multi-worker load/freshness still requires testing |
| Writes to snapshots triggered on dashboard reads | `wearables/services/analytics.py` | Dashboard GET produces read-only cards, while explicit worker refresh persists versioned snapshots |
| Wearable-only health timeline | `wearables/services/analytics.py` | Adds customer-owned Biopeak `ServiceResult` assessment/lab report date events with day-level precision and no fabricated biomarker values; remains partial vs PRD's complete diagnostics timeline |
| No consent withdrawal endpoint | `wearables/services/privacy.py`, `views.py`, `device_urls.py` | `POST /devices/revoke-consent/` revokes local consent, disconnects and queues API-provider revoke, blocks new ingestion, retains existing history |
| No raw-payload retention utility | `wearables/management/commands/purge_rook_raw_payloads.py` | Explicit dry-run-first command for **processed** historical raw payloads. Never run `--execute` before client approves policy, encryption and retention |
| Missing processed-event API recovery path | `wearables/services/client.py`, `job_processor.py`, client tests | Adds whitelist and bounded optional event recovery; **OFF by default** until actual ROOK response parameters and availability are confirmed |
| Frozen dependency mismatch in original minimal integration | `pyproject.toml`, `core/settings/base.py` | Removes added Redis dependency; uses built-in Django cache plus DB freshness revisions; original client `uv.lock` retained unchanged |
| Earlier SSL/bulk ingestion failures | `wearables/services/ingestion.py`, `job_processor.py` | Smaller 200-item inserts, eliminate high-volume per-reading source history lookups, recycle stale connections between jobs; Aiven connection drop still requires an actual staging verification |

## Phase 1 acceptance — remaining / outside this backend ZIP

These items **are not verified completed** and must not be represented as done without evidence:

1. **Runtime verification:** Python 3.14, `uv sync --frozen`, `manage.py check`, migration autodetector, migration plan and migration execution on PostgreSQL 17; full `wearables` and legacy regressions. This editing environment has Python 3.13 without Django and no dependency download network.
2. **Mobile/ROOK integration:** Real signed webhooks, ROOK authorization and revoke contract, source capabilities, mobile SDK connect/permission flow, native ~29-day pre-existing pull, end-to-end 7-day backend recovery. Only the Django backend is in this ZIP.
3. **Processed event fallback:** URL/parameter mapping in this release is intentionally opt-in (`ROOK_RECOVERY_INCLUDE_EVENTS=false`) until each event route and response shape are validated with ROOK; do not enable blindly.
4. **Complete clinical timeline:** Date-only existing `ServiceResult` events are present, but detailed lab numerical panels, imaging series, historical assessments and clinician displays require an approved cross-domain schema, dedicated permissions and integration tests.
5. **Production operations:** Install **Render Cron Job** (recommended safe starting command `python manage.py process_health_jobs --limit 5 --verbosity 2` every 5 minutes, adjust from observed runtime). Schedule freshness jobs; set correct database credentials and feature flags. Queue command alone is not an automatic worker.
6. **Aiven reliability:** Confirm previous SSL disconnects during >2000-reading jobs are resolved on representative payloads, and that health documents move `queued -> processed`, observations and daily summaries are populated for multiple profiles.
7. **Privacy, security, clinical sign-off:** DPDP retention, right-to-erasure, data residency, ROOK consent text, upstream vendor terms, source confidence thresholds and trend interpretation must be approved by the client. Revocation retains history and is not a full account erasure function.
8. **SLO and product:** No verified dashboard under-500ms/devices under-300ms p95, webhook success threshold, 7-/29-day import completion metric, comprehensive provider matrix, or the mobile/UX card-state acceptance. PRD remains marked *Draft for review*.
9. **GitHub source of truth:** Compare the patch to the **current client repository**; migration versions might differ from the uploaded historical original ZIP. Deploy via reviewed feature branch/PR, not overwrite.

## Verification commands

```bash
# Python 3.14 virtual environment, installed requirements and staging DB required
uv sync --frozen
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --plan
uv run python manage.py test wearables
uv run python manage.py test

# Syntax and pure-function tests that can run without Django/Python 3.14:
python scripts/check_phase1_static.py
python scripts/check_phase1_behavior_offline.py

# Optional, policy-gated retention review only (DO NOT run --execute without approval):
uv run python manage.py purge_rook_raw_payloads --older-than-days 90

# Isolated profile smoke test (limit one eligible job, not one observation):
uv run python manage.py process_health_jobs --customer-profile-id <UUID> --limit 1 --verbosity 2
```

## Required 7-day/30-day frontend checks

Request `GET /health/{heart,sleep,activity,body,recovery,workouts}/?days=7` and again `?days=30` using an owned customer-profile JWT. Verify `data.card.graph.points`, `data.metrics[*].points` and `data.historyWindowDays`. Test profile with 90 days, 5 days, no data, old data, granular events crossing local midnight, disconnected with retained history, and two sources with one denied. On dashboard, the six cards always use default **90-day** windows unless a detail range is explicitly requested.

## Change safety

See `PHASE1_MINIMAL_CHANGE_MANIFEST.csv` for exact added/modified files and original-preservation checks. No unrelated appointment, WhatsApp, Google Calendar, product, inventory or program business logic is intentionally ported from the larger updated ZIP. The six client syntax fixes are retained because those files otherwise fail Python AST parsing. A source-preservation comparison is not a substitute for full client regression tests.
