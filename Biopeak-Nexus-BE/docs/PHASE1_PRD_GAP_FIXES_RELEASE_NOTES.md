# Biopeak Nexus Phase 1: PRD gap-fix integration candidate

## Scope and source of truth

This candidate derives from `Biopeak-Nexus-BE-Phase1-PRD-Completion-Candidate.zip` and responds to the independent PRD-versus-ZIP audit. The original client legacy applications, their routes, authentication, database migrations and business logic were not changed by this correction pass. This is a **backend integration candidate**, not a certification that all Phase 1 acceptance tests passed.

## Corrected Phase 1 behavior

| PRD | Change |
|---|---|
| 5.3, 7.0, 7.7 | Identify Heart/HRV metrics by their field names before applying the containing ROOK Sleep/Physical pillar; retain supported sleep stages and ISO sleep session boundaries. |
| 7.0 | Member-facing health detail metrics use an explicit V1 allowlist. Unknown numeric ROOK fields can remain in canonical storage but are not displayed by default. Proprietary scores appear only when provided. |
| 7.2, 7.3, 7.4, EC-064 | Calendar eligibility and 7-day-vs-prior-28-day comparisons now use the member's current local date. Old records never unlock current recent windows. Confidence considers recency, coverage and sync health. |
| 7.1, 7.4 | Domain detail API accepts `window=7d|14d|30d|90d|lifetime`. Existing `days=...` remains supported. The response supplies server-calculated rolling averages, observation counts, availability and standard deviation without fabricating missing values. |
| 4.6, 7.5, 12.9 | Unique analytics refresh job key for each processed document/version/content digest; unrelated ROOK pillars for the same day cannot suppress each other's updates. Only affected domains are refreshed. |
| 4.5, 5.2.1, 10.1 | Recovery pull runs inside a retryable background worker; its documents are normalized and stored **before** successful import status is set. Partial/failed normalization sets partial or failed, not completed. |
| 5.3.1, 8.1 | `Unsupported` for documented incapable provider/domain pairs and `Waiting for Data` for capable or unknown pairs. Domain permissions continue to be treated separately from hardware capability. |
| 5.3, EC-104 | Provider selection and `/devices/connect/` both fail closed if the deployment's ROOK provisioned-provider list is absent. |
| 6.6, 12.5 | Read-through shared **database snapshots** when deployment uses local-memory cache; explicit snapshot invalidation following source or data changes. Shared backend cache still supported. SLA must be benchmarked. |
| 10.1, 10.2 | Hourly freshness/recovery scheduling keys and automatic expiry of abandoned pending OAuth handoffs when the periodic command runs. |
| 7.4, 10.2 | Timeline Historical Gap annotations calculate from the full requested date/domain range, not the returned page. |
| 7.6, EC-093 | Analytics algorithm version increased to `wearables-v1.1` so old snapshots are rejected and regenerated. No existing migration was rewritten. |

## Backend API compatibility

- Existing devices, dashboard and timeline endpoints remain registered; existing response fields are retained.
- `GET /api/v1/health/<domain>/?days=90` retains existing behavior and additionally supplies per-metric `rollingAverages` and `chartType`.
- `GET /api/v1/health/<domain>/?window=lifetime` returns all retained displayable summary dates; `window` overrides `days` when both are supplied.
- Sleep domain detail may now include `sleepSessions` with existing ROOK timestamp strings; missing start/end entries are omitted.
- `POST /api/v1/devices/connect/` now returns a validation error when `ROOK_PROVISIONED_SOURCES` is missing. Set the provisioned sources in staging/production before accepting new connections.
- ROOK historical import completion and failure state changes are intentional corrections, not legacy API changes.

## Deployment and acceptance runbook

1. Obtain separate client approval for the six inherited syntax-error files if they block startup. They remain untouched in this ZIP.
2. Use the project-defined Python 3.14+, frozen dependencies and a staging PostgreSQL database; never run destructive commands on production.
3. Set ROOK credentials, `ROOK_PROVISIONED_SOURCES`, callback URL, webhook secret, feature flags and pre-existing-data setting. Confirm provider provisioning with ROOK; the list must be explicit.
4. Run `uv sync --frozen` then `uv run python manage.py check`.
5. Run `uv run python manage.py makemigrations --check --dry-run` and `uv run python manage.py migrate --plan`, then migrate a temporary staging database.
6. Run `uv run python manage.py test wearables.tests` (including new `test_prd_gap_closure`). Run original client API regression tests too.
7. Run `uv run python manage.py recompute_health_algorithm --dry-run --limit 100` and then approved recomputation on staging to refresh algorithm v1.1 snapshots.
8. Schedule `uv run python manage.py enqueue_health_freshness_checks` **hourly** and `uv run python manage.py process_health_jobs --limit 50` sufficiently frequently for the webhook-processing SLA. Monitor job failures, blocked profiles, stalled imports, dashboard freshness and webhook signatures.
9. Exercise ROOK sandbox OAuth, a Garmin 7-day backfill, an SDK up-to-29-day backfill, multiple providers, correction/higher-version replay, out-of-order webhooks, disconnect/expiry, permission revocation, and delayed recovery.
10. Verify native Apple Health/Health Connect on real devices; benchmark dashboard (<500 ms), connected devices (<300 ms), worker throughput, and rollback with a production-like dataset.
11. Obtain client policy sign-off for DPDP account deletion, retention/residency, clinical thresholds and permitted sources. This release does **not** guess missing legal/clinical policy decisions.

## Verification limitations

All new/modified wearable Python parses on the available Python 3.13 interpreter. The supported project runtime is Python >=3.14, and this environment has no Django or staging PostgreSQL/ROOK credentials. The isolated code/function probes are not Django API or database integration tests; see the external verification report. Six unchanged client legacy Python modules contain inherited syntax errors that may block import. Therefore Phase 1 cannot be certified 100% production-compliant here.
