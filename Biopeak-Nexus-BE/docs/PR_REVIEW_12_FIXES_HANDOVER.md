# Phase 1 Wearables — Twelve PR Review Fixes (2026-10-19)

Baseline: user-supplied production archive `Biopeak-Nexus-BE(10).zip`. This patch is **only** the reviewer-requested wearables hardening and scheduler integration; do not overwrite live `.env`, `.git`, or Python virtual environments.

## Reviewer fixes (P0 = deploy blocker, P1 = high, P2 = coding/reliability)

| # | Priority | Reviewer request | Implemented change |
|---|---|---|---|
| 1 | P0 | Accepted ROOK payloads never processed in production | `assets/scripts/sweep_jobs.sh` calls both `enqueue_health_freshness_checks` and `process_health_jobs --limit 50`, preserves nonzero exit status; `docs/ENVIRONMENT.md` documents EventBridge schedule and backlog monitoring |
| 2 | P1 | `/devices/sdk-config/` exposes SDK secret | Separate client SDK credential must differ from server ROOK Basic-auth secret; explicit per-environment `ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC` approval (default false); response no-store; deployment readiness checks reject accidental server-secret reuse. Final authorization to distribute credential requires ROOK confirmation |
| 3 | P1 | Historical migration imports mutable constants | `wearables/migrations/0001_initial.py` freezes enums/choices/defaults as local migration literals; no additional migration or table change |
| 4 | P1 | Two concurrent webhook first-writers trigger unique constraint | `RookHealthDocument.objects.get_or_create(document_identity=...)` safely handles PostgreSQL duplicate inserts with Django's internal `IntegrityError` savepoint/re-query; newer versions promoted via conditional update |
| 5 | P1 | Daily summary N+1 latest metric query | Correlated `Subquery`/`OuterRef` retrieves latest numeric observation within a grouped database query; no per-metric query |
| 6 | P1 | Seven-day recovery may outlive 15-minute lease | Separate recovery lease respects 21 configured HTTP connect/read timeouts, plus safety margin; heartbeat during upstream calls and normalization; worker claims and completions are attempt-checked |
| 7 | P1 | Per-worker health cache goes stale on ECS | Health-specific cache uses `DummyCache`; DB snapshots are the canonical cross-worker read-through; existing legacy default cache untouched. DRF per-process throttling remains a deployment concern, addressed with WAF or shared backend before general availability |
| 8 | P2 | `select_for_update()` project violation | Removed wearable-service row locks; use filtered, conditional ORM writes and unique constraints, with stale state/revocation checks |
| 9 | P2 | Imports inside functions | Hoisted imports to the top of affected wearable modules (including views and serializers). Cyclic uses refer to other module objects instead of importing functions before initialization |
| 10 | P2 | Nested `walk()` in signature verifier | Replaced with module-level `_walk_metadata_datetime` helper |
| 11 | P2 | ORM `.get()` no-missing-row handling | Replaced flagged wearable service lookups with `.filter(...).first()` and explicit handling |
| 12 | P2 | Huge transaction during timezone remap | Remaps up to 500 observations per short transaction; checks timezone between batches; rebuilds affected day summaries in bounded transactions; never alters UTC instants |

## Required deployment work (cannot be completed from a source ZIP)

1. Provision EventBridge/ECS execution of `assets/scripts/sweep_jobs.sh` every 15 minutes; keep task concurrency at one per environment, ensure executable script and alerting. Do not assume `deploy-aws.yml` provisions EventBridge; it does not.
2. Set ROOK server API credentials, approved source list, callback HTTPS URL, webhook signing key and actual ROOK webhook subscriptions in staging/prod; run `uv run python manage.py check_rook_configuration --strict` without printing secrets.
3. If providing Apple Health/Health Connect, enable native SDK distribution only **after ROOK confirms the credential is intended for client-side use**; never reuse `ROOK_SECRET_KEY` as `ROOK_SDK_SECRET`. Default is to decline exposure.
4. Configure WAF/API Gateway throttling for wearable endpoints (the app's legacy default LocMem throttle is per worker); the health dashboard cache itself is deliberately disabled and backed by database snapshots.
5. Use Python 3.14 and a staging PostgreSQL database. Run `uv sync --frozen`, `uv run python manage.py check`, `uv run python manage.py makemigrations --check --dry-run`, `uv run python manage.py migrate --plan`, `uv run python manage.py test wearables.tests.test_pr_review_12_fixes`, then `uv run python manage.py test wearables.tests` and full regressions. Exercise live ROOK callback/webhook, concurrent duplicate deliveries, recovery over multiple timeouts, reconnect/consent revocation, and native iOS/Android SDK.

## Verification limits

Code syntax, schedule behavior, frozen choices, CAS updates and SDK fail-closed behavior can be verified by isolated source-level checks without live services. **No claim of full Django/PostgreSQL/ROOK production integration testing is made** by this artifact. Python 3.14, installed requirements, PostgreSQL and live ROOK provisioning are required to certify merge readiness. The original archive contained a local `.env`, `.venv`, and Git history; these are intentionally excluded from the delivery ZIP. Preserve your deployment values in a secret manager and never commit them.
