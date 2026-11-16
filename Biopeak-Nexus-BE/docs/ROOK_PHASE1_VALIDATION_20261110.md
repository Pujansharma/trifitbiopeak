# ROOK Phase 1 validation — 10 November 2026

## Executed

- Installed the unchanged dependency lock with `uv sync --frozen --python 3.14`. The runtime was Python 3.14.10. An initial unqualified sync selected Python 3.15 and failed on wheel availability; explicitly selecting 3.14 succeeded. Neither dependency file was changed.
- Executed **196 no-database tests**, all passed, using the real installed Django framework and all discoverable ROOK pure-unittest/SimpleTestCase classes. No test-module import errors remained. This includes 18 new policy/mocked-service regressions, existing sync/rate/deployment contracts, signature, callback, availability, configuration and timeline tests.
- Scoped Django system checks passed with one test-harness warning: Debug Toolbar middleware was deliberately absent. The temporary URL configuration included the existing ROOK endpoints and browser return routes, avoiding unrelated application credential setup. No fake database success is claimed.
- Original comparison established an obsolete `_page_gaps` test import and an inconsistent environment-prefix fixture. These ROOK tests were updated to exercise the existing full-range timeline and global-then-prefixed configuration contracts. Their assertions were retained and corrected for the actual contracts, not suppressed.
- New module/test lint checks passed. Updated Python source parsed on Python 3.14. Packaging checks verify source retention, allowed changed-file scope, unchanged protected files and no migration/model edits.
- The workbook was rendered and visually inspected. Its queue diagram is embedded. Release-action formulas were checked by changing one Pending input to Completed, observing 4 -> 3 outstanding actions, and restoring the original value. Formula error scan returned no matches.

## Included but not executed

Eight real ORM regressions in `wearables/tests/test_phase1_improvements.py` cover exhausted/legacy authorization, explicit reconnect generations, pending upstream identity, grant-time stability, Withings wait accounting, unchanged measurement time after an empty pull and late-worker fencing after disconnect. Existing PostgreSQL concurrency tests are retained.

A disposable embedded PostgreSQL startup was attempted outside the project. The execution environment rejected creation of its Unix socket with `PermissionError: Operation not permitted`. No client database was accessed. Therefore model creation, schema upgrade, SQL execution, DISTINCT ON batching, JSON/aggregate progress queries, sliced prefetches and concurrent transactions are **not validated here**. No database test was silently converted into a mocked pass.

Live ROOK authorization/webhooks/native SDK/revocation, actual entitlement/quota behavior, Redis/shared-cache behavior, AWS SQS/ECS/EventBridge/IAM and load performance were not exercised. Shared-cache tests use mocks. Syntax, pure policies and mock contracts do not establish production readiness.

## Required staging acceptance

1. Repository owner generates/reviews/applies migrations against the actual branch. The baseline schema inventory is supplied separately. This update adds no further model changes.
2. Run `uv run --python 3.14 python manage.py test wearables.tests --verbosity 2` with real PostgreSQL, followed by the owning application's required regression checks.
3. Run real connect -> available initial/live data -> manual sync -> empty check -> disconnect -> delayed provider confirmation -> reconnect. Verify timeline continuity and separate check/measurement times.
4. Exercise duplicates, corrections, webhook/worker races, quota deferral, worker termination, SQS wake loss and nightly coverage selection.
5. Confirm real provider quotas, history entitlement and reconnect-backfill behavior. Benchmark first usable data and full import completion separately. Keep the five-slot limit as a configured cap, not a capacity claim.

This package is an implementation candidate with explicitly incomplete staging validation.
