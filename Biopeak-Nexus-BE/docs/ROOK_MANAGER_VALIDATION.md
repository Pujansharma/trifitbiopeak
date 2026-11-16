# Validation and release limits

Prepared against `Biopeak_ROOK_Nov04_5_New_Review_Fixes_Final.zip` for the four manager diagrams. This is an implementation candidate, not a production-readiness or load-capacity certificate.

## Executed checks

| Check | Result and exact scope |
| --- | --- |
| Pure date/window/checkpoint tests | 16 passed under Python 3.13.5 using the actual `sync_plan.py`; includes initial/incremental/rolling windows, local dates and checkpoints. |
| Isolated supervisor and summary HTTP parsing | 15 passed. Executed the actual supervisor source with stubbed Django/database/lease dependencies and real child subprocesses; tested success, nonzero child exit, busy exit 75, deadline exit 124, failure-before-termination order, unavailable failure-recording DB, caller bypass rejection and old-owner fencing call order. HTTP parsing executed the actual extracted method against mocked responses, including empty HTTP failures. These were NOT live ORM/PostgreSQL tests. |
| Shell/template checks | 8 passed. Bash syntax; actual shell execution using a stub `python` command; original six shared commands and failure propagation; regular limit 5, recovery limit 1/deadline 780; midnight enqueue-only; YAML/template structure and script target existence. No AWS API deployment validation. |
| Modified/new Python syntax and global-name scan | No syntax errors or unresolved global names in changed/new Python files. This is static inspection, not import/runtime proof. |
| Full-source parse | 1,065 files parsed with Python 3.13.5. Six unchanged client files require Python 3.14's exception syntax and do not parse on 3.13; they were not edited. |
| Scope/integrity | See the packaged change manifest. Existing migrations, dependency manifests, API route files and deployment workflow were preserved. ZIP CRC/integrity checked when packaged. The Git patch was applied to a clean copy of the baseline; all 52 changed/added files matched the packaged source bytes. |

Total executed isolated/unit/script checks: **39**. None contacts ROOK, AWS or a customer database. The subprocess checks do not prove distributed ORM leasing; that requires the PostgreSQL tests below.

## Not executed / mandatory release gates

The environment did not contain Python 3.14, Django, psycopg, a PostgreSQL service or Docker. A Python 3.14 download failed with DNS/network failure; package installation also did not provide a usable Django environment. Consequently:

- `uv sync --frozen` on the exact Python 3.14-slim image was NOT executed successfully here.
- The full Django test suite, application imports, Django system checks and real database migrations were NOT executed here.
- New two-connection PostgreSQL race/lease tests are provided but NOT claimed passed.
- Live ROOK authorization, date-based history availability, webhook delivery and remote revoke timing are NOT verified here.
- Native mobile SDK behavior, AWS IAM/VPC/logging, EventBridge invocation and multi-ECS behavior are NOT verified here.
- No load or capacity test was run; this package does NOT establish 100,000-user capacity.

## Tests supplied in the repository

`wearables/tests/test_manager_flows.py` covers authorization verification, initial pulls, duplicate manual requests, durable checkpoints, analytics retry, bounded continuation, revoke races, nightly selection, failed revoke retries, stale owner fencing, and real PostgreSQL concurrency scenarios (not run here).

`wearables/tests/test_sync_plan.py` is the dependency-free planning/checkpoint test module (run here).

Existing ROOK tests for callback behavior, reconnects, remote revocation, worker limits and leases were updated where the manager design supersedes synchronous/80-minute/shared-worker expectations. Existing client tests and business implementations were not altered.

## Run in the approved staging environment

Generate and review the wearable migration first, as required by the repository's migration-ownership rule. Then run:

```bash
uv sync --frozen
uv run python manage.py check
uv run python manage.py test wearables.tests.test_sync_plan --verbosity 2
uv run python manage.py test wearables.tests.test_manager_flows --verbosity 2
uv run python manage.py test wearables.tests.test_pr143_nov04_review_worker_schedules --verbosity 2
uv run python manage.py test wearables.tests --verbosity 2
```

Use a disposable PostgreSQL test database and mocked provider calls for these suites. Do not point tests or migration experiments at the client's production database. Real-provider staging acceptance and the schedule smoke tests in `ROOK_MANAGER_FLOWS.md` remain separate steps.
