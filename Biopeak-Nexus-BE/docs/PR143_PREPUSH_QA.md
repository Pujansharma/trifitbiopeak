# Biopeak Nexus — pre-push quality checks for PR #143

## Why this is necessary

An isolated syntax/logic check is **not** proof that all application tests pass.
Review requests may come from human code review, static review, integration
failures, load/concurrency analysis or deployment requirements. The PR #143
reviewer's job-queue and multi-ECS findings are examples of cases that require
stateful testing or reasoning about multiple processes.

## Audit performed on the 2026-10-29 latest delivered ZIP

Baseline: `Biopeak-Nexus-BE-PR143-Freshness-Recovery-Redis-Final.zip`.
Compared with the preceding reconnect ZIP: **17 existing files modified,
2 new files, 0 deleted**. The Redis dependency is listed in both `pyproject.toml`
and `uv.lock`, but resolution has **not** been verified by `uv lock --check`.
There was no `.github/workflows/` workflow in this ZIP.

A repository-wide AST parse of 994 Python files found six syntax errors in
legacy/non-wearable exception handlers (all six also exist in the original
2026-10-27 user-uploaded archive):

- `products/views.py` line 65
- `accounts/centers/views.py` line 111
- `accounts/admins/views.py` line 71
- `programs/services/views.py` line 124
- `programs/services/therapy/views.py` line 104
- `programs/services/assessment/views.py` line 78

All six use `except ProtectedError, RestrictedError:` or the reverse, which is
not valid Python 3; the intended form is `except (ProtectedError, RestrictedError):`.
**The optional six-file syntax patch changes only those expressions.** Review
it separately before applying to the client's main branch.

## Run locally (PowerShell)

Use Python 3.14 and a disposable PostgreSQL **test** database. Ensure
`SECRET_KEY` and `DEV_DB_*` are configured, and that the database user can create
a separate Django test database. Never point these checks at production patient
records.

```powershell
./assets/scripts/test_before_push.ps1
```

The script fails immediately on syntax, lockfile, Django checks or a test failure.
It does not push, migrate production schemas or change any source files.

## Pull request checks

`.github/workflows/backend-ci.yml` runs on pushes to main and PR updates:

1. Repository-wide Python syntax parse.
2. Python 3.14 with PostgreSQL 17 in GitHub Actions.
3. Verify lockfile, Django system checks and five PR143 test modules.
4. Run all wearable tests and then the full Django test suite.

**Initial CI runs may fail** on further pre-existing DB/migration/environment
issues; address those failures individually, and do not weaken the gates to
make the build green. The author must enable required status checks in GitHub
branch protection. The workflow is proposed, not validated remotely.

## Staging checks outside GitHub CI

- ROOK sandbox: connect, disconnect, reconnect and historical sync.
- Webhook signature, duplicate event, normalization and recovery.
- Hundreds of active profiles in the hourly scheduler; no per-profile queue
  growth, fair scheduling, no duplicate recovery work.
- Two real ECS tasks must read/write the same Redis key. Confirm `default`
  uses ElastiCache and `health` remains `DummyCache`.
- Run database migration/history checks in an isolated copy of staging.
- Retest legacy APIs: auth, account management, appointments, products and
  program/service lifecycle endpoints, not only wearables.

## Verification limitations

This artifact environment has Python 3.13, not the required Python 3.14.
Installing Python 3.14 failed because the external package host was unreachable;
Django/PostgreSQL/Redis services and project dependencies are unavailable here.
The syntax-check script and its optional patch were tested locally; the full
Django suite and this GitHub Actions workflow **have not been executed here**.
