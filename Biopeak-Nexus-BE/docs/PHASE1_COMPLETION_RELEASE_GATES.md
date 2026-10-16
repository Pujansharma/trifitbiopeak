# Biopeak Nexus Phase 1 — PRD Completion Candidate and Release Gates

**Source baseline:** Biopeak-Nexus-BE(5).zip. **Implementation baseline:** Biopeak-Nexus-BE-Phase1-ROOK-Historical-Days-Fixed.zip.

**Status: BACKEND IMPLEMENTATION CANDIDATE, NOT 100% VERIFIED OR RELEASE APPROVED.** No live ROOK, native SDK, Django API, or PostgreSQL test was executed in the available environment. The original client's six syntax-error files were deliberately left unchanged pending client authorization.

## Phase 1 additions and corrections (October 2026)

- Per-source authorization, consent and disconnect checks at ingestion; identity alone never authorizes every provider. Each document must come from all identified currently authorized sources; unattributed data is accepted only where exactly one eligible source exists. Queued documents recheck consent/source before normalization; rejected receipts can be replayed following authorized recovery.
- Connection state graph and validated transitions: Connecting, Authorizing, Reconnected, Historical Re-import, Active, Partial, Idle, Expired, Disconnected, Provider Error. ROOK-positive notifications cannot reopen locally disconnected accounts. Disconnections close the local grant before the upstream network request.
- Provider-account deletion tracked as unrecoverable on the same connection and returns a Connect Another Provider action. A second tap on an already authorized connection does not re-import historical data.
- Scoped native permissions: previously granted Sleep is still available when Activity is denied. Native status may declare completion/partial/failure of historical import; subsequent grants do not restart a completed backfill.
- Historical recovery bounded to 7 days API and 29 days native SDK, additionally bounded to the recent reconnect gap for API pulls. Operator opt-in required for pre-existing imports in production; no synthetic history is created when unavailable.
- Dashboard states depend on actual baselines rather than raw observation counts, retain values on disconnect and provide low-confidence guidance. Mixed provider failure does not mask a healthy provider. Time-window availability uses calendar days. Worker-local cache is not treated as a shared cache across Gunicorn workers.
- Source-change and future clinician-review annotations in timeline, schema-drift audit events, operational status metrics, optional HTTPS aggregate-alert delivery, and operator-triggered versioned summary recomputation.
- Regression tests, consent fixtures, API provider-availability contract, and configuration helper. Existing legacy client APIs, authentication and business logic remain untouched in this update.

## New optional environment controls

- `ROOK_PREEXISTING_ENABLED=true`: required explicitly in production to permit ROOK pre-existing history; otherwise only live sync begins. Default true in sandbox, false in production. Historical days remain capped to ROOK's support limits.
- `ROOK_PROVISIONED_SOURCES=Garmin,Fitbit,Oura`: explicit provider allowlist needed to serve accurate provider availability via `GET /api/v1/devices/providers/`. If not configured, provider list reports provisioning *unverified* and advises mobile to disable selection; existing connect behavior remains compatible.
- `HEALTH_OPS_ALERT_WEBHOOK_URL=https://...`: optional HTTPS destination for aggregated operational alerts (no member health data).
- Existing `STG_*` / `PRD_*` ROOK, feature and webhook credentials still need to be supplied per environment as documented in `docs/PHASE1_ROOK_CONFIG.example`.

## Safe deployment sequence (staging only first)

1. Obtain separate client approval for the pre-existing six syntax errors, if they prevent Django startup. The original source files were deliberately not fixed here.
2. Use Python **3.14+** and the project's `uv` lockfile. Confirm `uv sync --frozen` succeeds. Resolve any Redis/shared-cache decision before enabling multiworker caching.
3. Set deployment ROOK credentials, signature key, SDK config, allowed hosts and explicit provider allowlist. Do not commit secrets. Set `ROOK_PREEXISTING_ENABLED=true` only after the corresponding ROOK feature is provisioned.
4. Back up the staging PostgreSQL DB. Run `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run python manage.py showmigrations wearables`, and `uv run python manage.py migrate --plan`. Apply **only** approved migrations on staging; never run destructive operations on production as a test.
5. Run `uv run python manage.py test wearables.tests`, plus the existing legacy API regression suite. Verify a profile cannot read another profile's data.
6. Mocked ROOK tests are not live proofs. On ROOK sandbox, test OAuth cancel, timeout, reconnect, provider-account deletion, signed webhook, duplicate, reordered version, disabled scope, import-disabled, and source disconnection with other provider still active.
7. On real iOS/Android devices, test HealthKit/Health Connect permission changes, reinstall/new-phone reauthorization, background delivery, DST and travel.
8. Schedule `uv run python manage.py enqueue_health_freshness_checks` (hourly or per operational policy) and `uv run python manage.py process_health_jobs` (frequent intervals, with one-or-more workers). Schedule `uv run python manage.py health_phase1_status --strict` and/or `uv run python manage.py notify_health_ops`; configure an actual alert destination and verify delivery.
9. After approving an algorithm-version update, dry-run `uv run python manage.py recompute_health_algorithm --dry-run --limit 100`; perform actual recomputation in bounded batches, retaining source observations and a DB backup.
10. Confirm dashboards, timeline, response status codes, original customer APIs, import cadence, alerts, job retry, and rollback plan on staging before production merge.

## Remaining external / policy acceptance gates

- **NOT TESTED:** real ROOK authorizer response variants, webhook signatures against live ROOK, native SDK, PostgreSQL migrations, full Django startup/API integration, legacy regression tests, load/latency SLA, deployed job scheduler, and operational alert delivery.
- **CLIENT DECISION REQUIRED:** personal health data retention/anonymization after account deletion and any cross-border residence/DPDP policy. Do not invent a deletion policy and do not modify the client's original account-deletion implementation without approval.
- **INFRA REQUIRED:** shared cache across production workers or explicit non-cached dashboard freshness/latency acceptance (local-memory caching is bypassed for correctness); alert endpoint; feature flags/ROOK provisioned providers; deployment secrets.
- **FRONTEND/MOBILE REQUIRED:** domain cards, provider selection, grant/regrant, native SDK, device migration, correct action rendering, and all user-facing edge-case copy from PRD §9–10.
- **LEGACY BASELINE ISSUE:** the original client ZIP contains six syntax-error files. They are unchanged in this ZIP and may block root Django imports. The prior separate approval-only patch can be evaluated by the client.

**Release status: NOT READY TO CLAIM 100% COMPLETE.** This ZIP is a substantially improved backend candidate and must not be represented as production verified without the gates above.
