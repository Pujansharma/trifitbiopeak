# Biopeak Nexus — Client-Safe Phase 1 Handover and Release Gate

**Date:** 15 October 2026. **Base:** original `Biopeak-Nexus-BE(5).zip`. **Reference:** `Biopeak-Nexus-BE-Phase1-PRD-Updated(2).zip`. **Scope:** original Biopeak PRD Phase 1/ROOK. **Verdict: NOT READY TO MERGE into production.**

This is a source-level integration/review candidate, **not a working or production-certified release**. The client-original backend contains six inherited Python syntax errors. Per the explicit protection rule they are unchanged in this ZIP. Live Django imports, database migrations, APIs and provider workflows have NOT been tested.

## Source preservation evidence

- Baseline files reviewed: **1098**. Final original files byte-for-byte identical: **1091**. Original modified files: **7**. Original files removed: **zero**.
- The existing OTP, JWT, users, customer-profile models/serializers/views, appointments, products, programs, inventory, Google Calendar, WhatsApp, and other legacy modules are identical to the original source. Original request/response shape cannot be runtime-certified without application startup.
- Six invalid `except Error1, Error2:` clauses inherited from the baseline remain unchanged. A separate **approval-only** patch is delivered outside the ZIP; it is NOT applied here.
- Original `pyproject.toml` and `uv.lock` stay byte-for-byte identical; no unrelated dependencies or upgrades. A distributed shared cache remains a production decision.

## A. New files added by the integration

| Path | Purpose |
|---|---|
| `accounts/customers/migrations/0020_customerprofilefeature_wearables_feature_choice.py` | Add wearable feature choice to existing profile rollout; does not add customer columns. |
| `accounts/organizations/migrations/0003_platformfeature_wearables_feature_choice.py` | Add wearable choice to existing organization rollout options; no data migration. |
| `docs/PHASE1_CLIENT_SAFE_HANDOVER.md` | Source preservation, test evidence, and deployment approval gates. |
| `docs/PHASE1_PRD_TRACEABILITY.csv` | Requirement-by-requirement evidence and remaining verification gates. |
| `docs/PHASE1_ROOK_CONFIG.example` | Environment variable names without credentials. |
| `docs/wearables-phase-1-backend.md` | New backend API/architecture description. |
| `wearables/__init__.py` | New wearables module/application registration scaffolding. |
| `wearables/admin.py` | New wearables module/application registration scaffolding. |
| `wearables/apps.py` | New wearables module/application registration scaffolding. |
| `wearables/callback_urls.py` | Short ROOK OAuth browser return URL after ROOK-appended client/member path. |
| `wearables/device_urls.py` | New additive /devices route tree. |
| `wearables/health_urls.py` | New additive /health route tree. |
| `wearables/management/__init__.py` | New wearables module/application registration scaffolding. |
| `wearables/management/commands/__init__.py` | New operational job runner / status or freshness scheduling command. |
| `wearables/management/commands/enqueue_health_freshness_checks.py` | New operational job runner / status or freshness scheduling command. |
| `wearables/management/commands/health_phase1_status.py` | New operational job runner / status or freshness scheduling command. |
| `wearables/management/commands/process_health_jobs.py` | New operational job runner / status or freshness scheduling command. |
| `wearables/migrations/0001_initial.py` | Create new wearables domain tables and constraints only. |
| `wearables/migrations/__init__.py` | New wearables module/application registration scaffolding. |
| `wearables/models.py` | Member identity, consent, connection and event, document, observation, daily summary, snapshots and processing jobs. |
| `wearables/serializers.py` | Validate connect, consent, source, redirect, domain, timeline parameters. |
| `wearables/services/__init__.py` | New wearables module/application registration scaffolding. |
| `wearables/services/analytics.py` | Six health domains, charts, baseline, cache and timeline facade. |
| `wearables/services/client.py` | ROOK server-to-server authorizer, status, historical summary and revocation HTTP client. |
| `wearables/services/connections.py` | Connection lifecycle, authorization, disconnect and native status transitions. |
| `wearables/services/consent.py` | Member opt-out and history-preserving connection shutdown. |
| `wearables/services/identity.py` | Stable ROOK identity based on existing owned customer profile. |
| `wearables/services/ingestion.py` | Signed ROOK document validation, idempotent persistence, correction handling. |
| `wearables/services/job_processor.py` | Recover data and compute analytics using retryable database jobs. |
| `wearables/services/job_queue.py` | Idempotent job scheduling. |
| `wearables/services/metrics.py` | Canonical metric extraction and provider-independent observations. |
| `wearables/services/notifications.py` | Deduplicated ROOK notification handling. |
| `wearables/services/oauth.py` | ROOK-compatible redirect path and one-time hashed CSRF/identity check. |
| `wearables/services/provenance.py` | Normalize source metadata without rebuilding ROOK provider logic. |
| `wearables/services/signature.py` | ROOK HMAC signature verification and metadata timestamp. |
| `wearables/services/timeline.py` | Merge canonical wearables with read-only client clinical milestones per profile. |
| `wearables/tests/__init__.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_analytics.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_client.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_client_safe_integration.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_ingestion.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_metrics.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_notifications.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_phase1_regression.py` | New focused test module; Django runtime execution pending. |
| `wearables/tests/test_signature.py` | New focused test module; Django runtime execution pending. |
| `wearables/utils/__init__.py` | New wearables module/application registration scaffolding. |
| `wearables/utils/constants.py` | Health domain, source, state and job enums for new Phase 1 models. |
| `wearables/views.py` | Member-scoped device APIs, dashboard/detail/timeline, consent revoke and callback. |
| `webhooks/rook/__init__.py` | New wearables module/application registration scaffolding. |
| `webhooks/rook/urls.py` | New signed webhook routes. |
| `webhooks/rook/views.py` | Signed health-data/notification receipt endpoints. |

## B. Original files changed — ONLY SEVEN

| Original path | Exact change | Why mandatory / if reverted | Existing API impact |
|---|---|---|---|
| `accounts/organizations/utils/constants.py` | Add WEARABLES feature choice for existing rollout checks. | Feature flag gating cannot reference the new choice; no existing route or business rule changed. | Additive only at source level; runtime untested |
| `core/api/urls.py` | Register /devices/, /health/ and short /r/ callback namespaces. | No new member route or ROOK callback can resolve; all original route declarations remain. | Additive only at source level; runtime untested |
| `core/settings/base.py` | Install wearables Django app, rate scopes, isolated health cache and health baseline settings. | New models will not register; rate scopes/cache alias will be undefined. | Additive only at source level; runtime untested |
| `core/settings/development.py` | Append local ROOK flags/config and two CORS header names. | Development settings cannot access credentials/feature controls and browser profile header may be blocked. | Additive only at source level; runtime untested |
| `core/settings/production.py` | Append production ROOK flags/config and two CORS header names; feature remains OFF by default. | Production cannot configure optional ROOK integration and its safe rollout. | Additive only at source level; runtime untested |
| `core/settings/staging.py` | Append staging ROOK flags/config and two CORS header names. | Staging lacks ROOK secret/settings and controlled rollout support. | Additive only at source level; runtime untested |
| `webhooks/urls.py` | Register new /webhooks/rook/ namespace. | ROOK delivery endpoints are unreachable; existing webhook routes remain. | Additive only at source level; runtime untested |

## C. Original code protected

Every other original path, including `accounts/users/**`, `accounts/customers/**` (existing files), `appointments/**`, `products/**`, `programs/**`, `inventory/**`, `diagnostics_orders/**`, `integrations/**`, `external/**`, `pre_consultation/**`, and existing URL and webhook handlers remains byte-identical. Two NEW choice migrations under customer/organization paths are exceptions as *added files*, not edits to client migrations.

## D. Updated ZIP changes intentionally excluded

- Unrelated appointment flows, products, inventory, programs, profile serializer/model, Google Calendar, WhatsApp, external integration changes, and unrelated migrations.
- Line-ending-only CRLF/LF rewrites (previous source audit reported 854) and broader refactors (previous audit reported 102 substantive changed files).
- Earlier six-line original syntax repairs: excluded **despite known startup failures**, pending client approval. No modified historical migrations.
- Any unrelated dependency updates, rewritten `uv.lock`, new customer height/weight columns or production data mutations.

## E. Pre-existing client issues left intact (approval required)

| Baseline file | Line | Problem |
|---|---:|---|
| `accounts/admins/views.py` | 71 | Original invalid comma-separated `except` syntax |
| `accounts/centers/views.py` | 111 | Original invalid comma-separated `except` syntax |
| `products/views.py` | 54 | Original invalid comma-separated `except` syntax |
| `programs/services/views.py` | 124 | Original invalid comma-separated `except` syntax |
| `programs/services/assessment/views.py` | 78 | Original invalid comma-separated `except` syntax |
| `programs/services/therapy/views.py` | 87 | Original invalid comma-separated `except` syntax |

**Consequence:** client startup might fail while importing these legacy endpoints under Python 3.14. This blocks certification of both original and new APIs, but cannot be fixed under the source-preservation rule without client approval. The separate patch shows only the six proposed parentheses fixes; it is not part of the final ZIP.

## New HTTP endpoints (additive routes)

| Method | Endpoint | Auth | Backend behavior | Test status |
|---|---|---|---|---|
| GET | `/devices/` | Biopeak customer JWT | Connection statuses; `?refresh=true` calls ROOK | **NOT TESTED** |
| POST | `/devices/connect/` | JWT | Consent + new API authorizer/native SDK connection | **NOT TESTED** |
| POST | `/devices/disconnect/` | JWT | History-preserving provider revoke | **NOT TESTED** |
| POST | `/devices/consent/revoke/` | JWT | Explicit member consent revoke and provider shutdown | **NOT TESTED** |
| POST | `/devices/retry-sync/` | JWT | Idempotent recovery job | **NOT TESTED** |
| GET | `/devices/sdk-config/` | JWT | Authorized native SDK config | **NOT TESTED** |
| POST | `/devices/native-status/` | JWT | SDK permission and connection state | **NOT TESTED** |
| GET | `/r/{state_token}/client_uuid/{client_uuid}/user_id/{rook_user_id}` | Public, one-time token | Checks token/client/user, authenticates ROOK server-side | **Isolated state checks only** |
| GET | `/health/dashboard/` | JWT | Six stable health domains | **NOT TESTED** |
| GET | `/health/{domain}/` | JWT | Domain detail/graphs/baselines | **NOT TESTED** |
| GET | `/health/timeline/` | JWT | Wearables + profile-scoped lab/assessment milestone union | **Isolated merge/order checks only** |
| POST | `/webhooks/rook/data/` | Signed HMAC | ROOK document ingestion/corrections/jobs | **Isolated HMAC checks only** |
| POST | `/webhooks/rook/notification/` | Signed HMAC | ROOK lifecycle status receipts | **Isolated HMAC checks only** |

## PRD Phase 1 coverage

The attached `PHASE1_PRD_TRACEABILITY.csv` contains **53 requirements** with implementation paths, endpoint contracts, status, and missing acceptance evidence. Broad Phase 1 source coverage includes connection/authorization, identity, consent, SDK state, initial import, continuous webhook, idempotent persistence, six-domain dashboard, detail, canonical timeline, read-only client lab/assessment events, baseline trends, and operational recovery/monitoring. Production acceptance cannot be marked complete because Django, DB, native SDK and external ROOK were not executed. Later-phase deep analytics, insights/clinician view, AI and unified Health OS remain out of scope.

The client-original lab timeline view intentionally exposes only a **milestone/availability event**, not protected lab report contents. It uses existing `ServiceResult` and `DiagnosticOrderCustomer` tables with profile-owned relationship filters and no original schema modification. Record-creation timestamps are not identical to sample/collection/report release dates; clinician/product validation and live query testing remain required.

## ROOK callback and provider contract

- The current ROOK authorizer API documents `redirect_url` max 50 characters, and appends `/client_uuid/<client_uuid>/user_id/<user_id>` to its **path**. We use `ROOK_CALLBACK_URL=https://short-approved-host/r` and append a cryptographically random 16-character path nonce; too-long URLs are rejected before database changes. Callback route is registered as `/r/` and verifies client UUID, ROOK member ID, one-time nonce, expiry and ROOK server-side authorization.
- If short callback host cannot be deployed, omit `ROOK_CALLBACK_URL` and let the authenticated frontend poll `/devices/?refresh=true`; do not assume redirect success.
- The published ROOK v1 per-provider authorizer supports Garmin, Oura, Polar, Fitbit, Withings, Whoop and Dexcom. Strava authorization is explicitly rejected by the new serializer instead of making an upstream unsupported API call.
- ROOK webhook signature uses nested metadata timestamps, webhook secret and exact source identity, plus idempotent notification/document receipts. All live variants/SDK behavior remain pending sandbox validation.

## Migration and environment requirements

- Added `accounts/organizations/migrations/0003_platformfeature_wearables_feature_choice.py` and `accounts/customers/migrations/0020_customerprofilefeature_wearables_feature_choice.py` — choices-only, no legacy profile columns.
- Added `wearables/migrations/0001_initial.py` — new wearables-related tables/constraints only, dependency on existing customer migration. Dependencies statically resolve; actual `makemigrations --check`, `migrate --plan` and temporary PostgreSQL migration are **NOT TESTED**.
- Use Python **3.14+** and existing `uv.lock` per original project. The working environment has Python **3.13.5** and lacks Django/test PostgreSQL; dependency install not available offline.
- Provide `ROOK_CLIENT_UUID`, `ROOK_SECRET_KEY`, `ROOK_WEBHOOK_HASH_KEY` and optional SDK and short callback settings in the secret manager with `DEV_`, `STG_`, `PRD_` prefix as appropriate. See `PHASE1_ROOK_CONFIG.example`. NEVER publish secrets.
- Register ROOK data and notification webhook URLs, ROOK device/source app approvals, worker schedule `process_health_jobs` and freshness status command. Set `WEARABLES_ENABLED=False` during deployment and enable only after verified acceptance.
- The health cache is `LocMemCache` (per process). It does **not** provide cross-worker invalidation. Use an approved shared cache or turn off/cache very short until multiworker concurrency is validated; no new Redis dependency has been added to avoid lockfile divergence.

## Testing: executed vs NOT TESTED

**Executed:** `python verify_release.py` as a source hash/AST/route/migration-dag and isolated pure-function checker; **13 of 13 checks passed** before final documentation additions. Python 3.13 `ast.parse` of all Python sources reports exactly the six known inherited syntax failures and zero new syntax failures. Pure nested webhook-HMAC checks (valid/bad/missing), OAuth token format/URL limit, and timeline merge/date-gap logic passed. Zip CRC is separately verified at packaging.

**Attempted and failed:** `python manage.py check` -> `ImportError: Couldn't import Django.` This is environment-related. The inherited six syntax errors are source-based independent blockers after Django installation.

**NOT TESTED:** `uv run python manage.py check`; `uv run python manage.py makemigrations --check --dry-run`; `uv run python manage.py migrate --plan`; temporary PostgreSQL apply/rollback; Django unit tests; legacy HTTP regression tests; live ROOK authorizer/callback/revoke; webhook portal signature variants; mobile native SDK and E2E; user ownership with actual profiles; throughput and distributed cache behavior.

### Proposed client-approved acceptance commands

```bash
uv sync --locked
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate --plan
uv run python manage.py test wearables
uv run python manage.py test accounts customers
uv run python manage.py process_health_jobs --help
uv run python manage.py health_phase1_status --help
```
Verify test package paths against the actual project, run all original API regression tests and apply wearable migrations only to a temporary PostgreSQL copy. The approval-only syntax patch may be required before any of these commands can load all URL modules.

## GitHub handover / release sequence

1. Open a separate review branch. Extract the final ZIP without replacing unrelated client source. Compare only seven edited original files plus new files and review the supplied patch.
2. Request **explicit written client approval** for six inherited syntax repairs if startup is blocked, separately from this Phase 1 PR. Do not silently merge the approval-only patch.
3. Provision Python 3.14, the original locked dependencies, and an isolated PostgreSQL test copy. Apply and test the added migrations on that copy.
4. Verify all original authentication/OTP/profile/program endpoints and every new device/health/webhook endpoint with valid and invalid users/payloads.
5. Test complete ROOK sandbox OAuth handoff, callback, webhook signature/replay and idempotency, recovery, disconnect/reconnect, consent revoke; verify mobile SDK and history.
6. Set approved HMAC/config/allowed hosts and background worker; choose shared-cache design and clinical/privacy/retention controls. Keep global and per-profile rollout flags OFF until acceptance.
7. Stage deployment with DB backup and migration plan. Roll back code/feature flags first; never reverse migrations or drop observation tables without a reviewed data-retention/data-loss plan.

## Final decision

**NOT READY TO MERGE into client production GitHub / deploy today.** Source-only review branch is suitable. No statement here certifies that all Phase 1 PRD requirements, existing APIs, or ROOK integration work end-to-end. Essential prerequisites include client decisions on inherited startup fixes and runtime/security/migration/SDK acceptance.
