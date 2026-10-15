# Biopeak Nexus / ROOK — Phase 1 PRD Delivery Status

**Basis:** `Biopeak Longitudinal Health Platform — PRD(1).html` (v1.0) and the Phase 1 Foundation plan.
**Scope:** Existing Django backend only. This patch does not contain the React Native mobile app or a live ROOK/production environment.

## Implemented in this ZIP (source-level)

- [x] Preserve existing Django architecture, Biopeak JWT, owned `CustomerProfile`, and PostgreSQL data model.
- [x] Register six fixed-order health domains and provider-agnostic dashboard, detail, timeline and device endpoints.
- [x] Support ROOK OAuth authorizer, mobile SDK setup/status reporting, HMAC-signed data/notification webhooks.
- [x] Correct ROOK document idempotency identity to member + data_structure + UTC datetime; apply higher-version corrections, reject lower/same-version conflicts.
- [x] Retain superseded `HealthObservation` versions for audit; exclude superseded versions from materialized summaries and user-facing timeline.
- [x] Keep observation instants UTC; aggregate using member's local date; queue remapping when member timezone changes.
- [x] Keep API pre-existing recovery at <=7 days; accept <=29 days for native SDK, which must import on device.
- [x] Preserve import-running status while progressive measurements arrive; do not treat one webhook as full backfill completion.
- [x] Use calendar dates in rolling trend windows, mark insufficient baseline explicitly, and suppress health interpretations when confidence is low.
- [x] Use provisional percentage-based minimum meaningful change for steps, weight, and stress; do not infer weight/body fat health benefit without a program goal.
- [x] Convert known V1 units in Biopeak API presentation, not in the client.
- [x] Emit timeline page-local missing-data intervals; no interpolation or zero-filling.
- [x] Expose recovery action via `POST /devices/retry-sync/` for API sources.
- [x] Use the built-in Django health cache with short TTL and database-backed revision keys across processes; no additional Redis dependency.
- [x] Add source-change provenance and temporarily suppress interpretation for recently changed metric sources.
- [x] Add `wearables/migrations/0001_initial.py` and regression tests for corrections, remapping, MMC, insufficient baseline, cache invalidation.
- [x] Add privacy-safe operational status command `health_phase1_status` for cron/support checks, `purge_rook_raw_payloads` as a dry-run-first retention utility, and profile consent withdrawal.
- [x] Fix six pre-existing invalid Python multi-exception clauses across products/programs/accounts modules, uncovered by full-repository syntax validation.

## Not completed or not verifiable solely from the backend ZIP

- [ ] **Migration validation on PostgreSQL 17:** Run Django's migration autodetector and migration checks. The environment used to create this ZIP had Python 3.13 and could not download Python 3.14/dependencies. The included migration is source-generated and has not been applied to the real schema.
- [ ] **Live ROOK authorization, signed webhook delivery and replay:** Requires client_uuid, secret, webhook hash, allowed callback URL, and working ROOK account.
- [ ] **Full 29-day SDK backfill:** Backend accepts up to 29 days for SDK sources, but the SDK's actual on-device history extraction and permission prompts must be implemented and tested in the React Native project.
- [ ] **React Native UI:** Six cards, device list, provider connection WebViews, SDK permissions, all card-state rendering, graphs, domain details, and E2E UX are outside this backend ZIP.
- [ ] **PRD 16-versus-14 state discrepancy:** PRD describes 14 states in headings yet explicitly enumerates 16 in Section 9.1. Implementation retains all 16; client/design sign-off is required.
- [ ] **ROOK metric support mapping:** Capability and permission granularity must be confirmed against actual provider test payloads. Do not assert unsupported/permission-required per metric without reliable upstream evidence.
- [ ] **Unified timeline:** Existing ServiceResult assessment/lab report dates are now included as date-only events, without invented biomarkers. The complete laboratory/diagnostic measurements and clinical event contract still require approval and mapping.
- [ ] **Full source-change confidence methodology, program-specific goals, clinical MMC:** Current values are provisional; require clinical agreement and reference data.
- [ ] **Production observability:** The included status command exposes useful aggregate metrics and alerts, but cron deployment, APM/dashboard latency instrumentation, alert routing, on-call ownership, and SLAs must be operated in staging/production.
- [ ] **Data-protection compliance:** Consent withdrawal now disconnects locally, queues API revocations, blocks fresh ingestion, and retains history. The optional `purge_rook_raw_payloads --older-than-days N --execute` command is manual only. Client approval for retention, data residency, DPDP account erasure, consent copy, and vendor governance is still required.
- [ ] **End-to-end performance, load, regression and staging demonstrations:** Must be run with actual PostgreSQL, ROOK and mobile clients.
- [ ] **Dependencies:** Removed the unresolvable additional Redis dependency. The original 35 locked dependencies match pyproject.toml metadata; run `uv sync --frozen` in a Python 3.14 environment to confirm.

## Installation and validation (required before claiming client acceptance)

Use **Python 3.14+** and **PostgreSQL 17**. Redis is not required by this ZIP. Preserve existing DB and authentication; take a DB backup before migrating.

```bash
# From the extracted repository root (Internet access required for deps):
uv python install 3.14
uv sync --frozen

# Provide SECRET_KEY, DEV_DB_*, ROOK credentials and webhook hash in .env
# Use staging/production-specific variables when not using dev settings.
export DJANGO_SETTINGS_MODULE=core.settings.development

uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --plan
uv run python manage.py migrate
uv run python manage.py test wearables.tests
uv run python manage.py process_health_jobs --limit 50
uv run python manage.py health_phase1_status --hours 24 --strict
```

**Background processing:** schedule `process_health_jobs` frequently (e.g., every minute) and `enqueue_health_freshness_checks` daily. A management command existing in code does not itself create a worker deployment.

**Health cache:** Health cards use Django LocMemCache per process. A database revision token changes when documents, identities, or connections change; confirm multi-replica consistency and performance under load. Shared Redis can be added later if required.

**ROOK webhook:** deliver to `/webhooks/rook/data/` and `/webhooks/rook/notification/`, use HMAC header per ROOK payload contract, and never enable unsigned webhooks in production.

**New retry route:** authenticated `POST /devices/retry-sync/`, body `{ "data_source": "Garmin" }`. For Apple Health/Health Connect, trigger synchronization through the mobile ROOK SDK rather than calling this server recovery route.

## Out-of-scope future phases

Phase 2: deeper analytics/comparisons. Phase 3: clinician insights/notifications. Phase 4: AI scores and prediction. Phase 5: expanded Health OS. They should not block Phase 1 foundation acceptance unless formally moved into Phase 1.

## Testing performed when packaging

- Python 3.13 AST parsing and `compileall` of all source Python modules (syntax-level only).
- Static checks of required routes, migrations, PRD Phase 1 code paths, and ZIP integrity.
- **Not** Django migrations/test execution against PostgreSQL or live ROOK E2E (dependencies and credentials were unavailable). An additional dependency-free behavior harness runs pure timestamp/window/provider-state checks.

**Delivery status:** Phase 1 source improvements included, but **not yet externally verified or signed off**. Check the unchecked release gates before declaring all Phase 1 ticks complete.
