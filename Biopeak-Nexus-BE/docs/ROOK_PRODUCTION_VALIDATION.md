# ROOK parallel-worker validation - 2026-11-06

> Historical validation for the original package. See [ROOK_PHASE1_VALIDATION_20261110.md](ROOK_PHASE1_VALIDATION_20261110.md) for the current candidate, executed tests and remaining release checks.

## Executed in this environment

- 69 offline unittest cases PASSED: existing 16 sync-plan cases, 38 new pure policy/
  coverage cases, and 15 offline deployment-contract cases. Run:
  `python -m unittest wearables.tests.test_sync_plan wearables.tests.test_production_policy wearables.tests.test_rook_deployment_contract -v`.
  These do not import Django or use PostgreSQL/AWS/ROOK.
- 9 isolated supervisor-helper checks PASSED. A separate harness extracted the actual
  `child_worker_command` and `stop_process_group` functions. CommandError was stubbed;
  subprocess termination/escalation used real local processes. This is NOT a test of
  Django supervision, ORM ownership, multiple ECS containers, or database failures.
- 34 changed/new Python modules parsed and compiled on Python 3.13.5. Production
  requires the repository's Python 3.14 image, which has NOT been certified here.
- Modified/new shell scripts passed bash syntax checks.
- Three ROOK infrastructure templates parsed; invariants for separate encrypted
  queues, disarmed services/schedules and no 15-minute recovery timer passed.
- Two generated ECS task definitions passed the installed botocore
  RegisterTaskDefinition input-shape validator using synthetic non-secret input.
  This does NOT establish CloudFormation/IAM/deployment validity in the client account.
- Static check found no select_for_update/raw SQL or nested function/import additions
  in changed implementation modules. Client business scope and migrations are unchanged.
- Final packaging checks verify no source deletions, unrelated changes, secrets/caches
  in the distribution; patch application and content hashes are reported in the
  external change register/manifest.

## NOT executed - mandatory release gates

- Python 3.14-slim Docker build or complete `uv sync --frozen` install.
- Full Django import/system checks, migration generation/application or full test suite.
- Actual PostgreSQL concurrency, partial unique constraint and rolling-worker shutdown.
- Live ROOK authorization, history availability, rate limits, signatures or revocation.
- Native SDK permission/synchronization and end-to-end mobile behavior.
- Real SQS, CloudFormation, ECS, EventBridge, IAM, VPC, alarms or service rollout.
- Any benchmark promising a first-data time, completed-import time or 100K-user capacity.

The environment lacks Django, psycopg, PostgreSQL and Docker. Attempts to download
Python 3.14 and Django dependencies failed due to network/DNS restrictions. Those
failures are not application test failures, and are not represented as successful
installation. No production database, credential or AWS account was used.

## Real integration tests included for owner execution

`wearables/tests/test_parallel_rook_workers.py` supplies ORM tests for five-slot cap,
legacy cutover, per-connection claims, token fencing, cooldown, coalesced follow-up,
retry budget, durable wake failure, sent-wake semantics and shared HTTP admission.
Its TransactionTestCase uses ten independent PostgreSQL connections to contend for
five slots. This test has NOT been run here. Existing manager-flow tests were updated
to the six-hour admission policy and coverage-based nightly selection.

Run the FULL wearable suite, not only the added tests, after reviewed migrations.
Existing client tests outside ROOK must be run by the owning team too. Any failure
requires investigation; do not suppress a failing test to declare release readiness.

## Production acceptance / owner signoff

1. Review and commit migrations on the actual current client branch, test upgrade on a
   staging copy, validate no duplicate RUNNING recovery rows, back up, then apply.
2. Confirm manual policy and nightly interpretation; approve history entitlement and
   provider date/retention/timezone semantics. Set real allocated API budgets.
3. Deploy queues and disarmed dedicated consumers with correct roles/network/secrets.
4. Validate dropped/duplicate wakes, worker termination, late owner, revoke races,
   provider 429s, newer manual targets and analytics recovery in real PostgreSQL/ECS.
5. Measure ten simultaneous connections and then staged higher traffic. Check both
   first usable data and full history, plus impact on shared Biopeak DB connections.
6. Disable old ROOK schedules; enable one recovery consumer, then increase toward five.
7. Configure alerts and rehearse rollback. Preserve consent cleanup and accepted jobs.

Only after these gates pass should this candidate be considered for production.
