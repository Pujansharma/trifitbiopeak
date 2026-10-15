# Biopeak Nexus: eight test users + ROOK smoke testing (VS Code / Aiven / Render)

**Scope:** This package fixes the eight *synthetic customer* account setup and its use with customer-only `/devices/` and `/health/*` APIs. It deliberately does **not** remove permissions from other admin, associate, or center-specific APIs. Success of real ROOK connection, webhook ingestion and health metrics still depends on approved ROOK credentials, an authorized data source, consent, jobs and real data.

**Security:** Use a SEPARATE Render **staging** service and a SEPARATE Aiven **test** PostgreSQL database. Never seed a client's live database. Do not expose the direct phone login endpoint in production. Do not put the test-login key in your distributed mobile app or commit it to Git.

## Changes in this ZIP

- `accounts/verifications/views.py`: `/auth/login-phone-direct/` requires the explicit dev/staging flag and a strong `X-Test-Login-Key` header. Disabled in production and when the key is missing/weak.
- `accounts/verifications/serializers.py`: only the eight synthetic phone/email identities with an active customer role and primary profile may use the bypass.
- `accounts/verifications/utils/direct_login_testing.py`: single canonical allowlist and environment guard.
- `accounts/users/management/commands/seed_direct_login_test_users.py`: idempotently creates eight `User`, `Customer`, customer-role `UserAccount`, main `CustomerProfile` and `CustomerProfileFeature.enabled_tabs=['wearables', ...]`; refuses conflicting real accounts and requires staging confirmation.
- `accounts/users/management/commands/verify_test_phone_setup.py`: read-only checks for test accounts, permissions, flags, and DB tables.
- `core/settings/{base,development,staging}.py`: default-deny test login config; special rate limit; optional Aiven SSL mode setting in staging. Production retains disabled defaults.
- `bruno/environments/Staging-Test.bru` and `bruno/Auth/Login Phone Direct.bru`: testing environment and required header.
- `accounts/verifications/test_direct_login_testing.py`: no-database unit tests of the direct login gate.
- Six existing deletion handlers in `accounts/admins/views.py`, `accounts/centers/views.py`, `products/views.py`, `programs/services/views.py`, `programs/services/assessment/views.py`, and `programs/services/therapy/views.py`: corrected invalid Python `except A, B` syntax to `except (A, B)` without changing deletion behavior. Those syntax errors were present in the uploaded source.
- Cleared a stale hardcoded JWT from Bruno's Development environment; login saves fresh tokens at runtime.

There are **no Django model/schema changes** from this patch. The *uploaded original ROOK module* has **no `wearables/migrations/` directory**: migrations must be generated/reviewed by the project's migration owner before using those DB-backed APIs. This release does not claim to have applied migrations to your Aiven database.

## 1. Setup in VS Code on Windows

Open the folder containing `manage.py` in VS Code > Terminal > New Terminal (PowerShell).

1. Ensure **Python 3.14** and [`uv`](https://docs.astral.sh/uv/) are installed. The project requires Python >=3.14; Python 3.13 is not enough.
2. Run `uv sync --frozen` to install packages from the unchanged `uv.lock`.
3. Copy `.env.example` to `.env`, then add the **staging** variables below (or configure these as shell environment variables). Keep `.env` out of Git.

```powershell
uv sync --frozen
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Copy the generated random string into the matching `STG_TEST_PHONE_LOGIN_KEY` value in both your **local** `.env` and **Render staging** environment. It must be at least 32 characters, should be unique per staging environment, and must remain secret. Example variable names, NOT working credentials:

```dotenv
DJANGO_SETTINGS_MODULE=core.settings.staging
SECRET_KEY=<existing Django secret key; keep consistent with Render tokens>

# Aiven STAGING / TEST database (do not connect this configuration to production!)
STG_DB_NAME=<test database name>
STG_DB_USER=<test database user>
STG_DB_PASSWORD=<test database password>
STG_DB_HOST=<Aiven host>
STG_DB_PORT=<Aiven port>
STG_DB_SSLMODE=require

# The secure, restricted testing shortcut (disable after testing)
STG_TEST_PHONE_LOGIN_ENABLED=True
STG_TEST_PHONE_LOGIN_KEY=<your random 32+ character secret>

# Customer ROOK API access (existing flags; enabled only in staging)
STG_WEARABLES_ENABLED=True
STG_WEARABLES_REQUIRE_PROFILE_FEATURE=True
STG_TIMELINE_ENABLED=True
STG_ROOK_ENVIRONMENT=sandbox
STG_ROOK_BASE_URL=https://api.rook-connect.review

# Configure for LIVE ROOK connection/ingestion testing; optional for empty-state GETs
STG_ROOK_CLIENT_UUID=<ROOK sandbox client UUID>
STG_ROOK_SECRET_KEY=<ROOK sandbox server secret>
STG_ROOK_WEBHOOK_HASH_KEY=<ROOK sandbox webhook verification key>
# Native SDK only, if testing Apple Health / Health Connect / Samsung Health:
STG_ROOK_SDK_CLIENT_UUID=<ROOK mobile SDK UUID>
STG_ROOK_SDK_SECRET=<ROOK mobile SDK secret>
```

**Other staging settings are still required.** This Django project also loads `STG_EMAIL_*` and AWS S3 settings at import time. Retain or configure the existing `STG_EMAIL_HOST`, `STG_EMAIL_PORT`, `STG_EMAIL_HOST_USER`, `STG_EMAIL_HOST_PASSWORD`, `STG_DEFAULT_FROM_EMAIL`, `AWS_S3_ACCESS_KEY_ID`, `AWS_S3_SECRET_ACCESS_KEY`, `AWS_STORAGE_BUCKET_NAME`, `AWS_S3_REGION_NAME`, `AWS_S3_CUSTOM_DOMAIN` values from your backend's staging handover. This ZIP does **not** change those dependencies or require switching from Aiven to a new database.

## 2. Confirm the staging database before any writes

Make sure the command is running with staging settings and the **separate test Aiven DB**:

```powershell
uv run python manage.py check --settings=core.settings.staging
uv run python manage.py showmigrations --settings=core.settings.staging
```

**Critical missing step from the uploaded original:** `wearables` currently lacks migration files. Per the repo's policy, migration generation/review is done by the project's owner. On your local branch, have the owner generate the migrations:

```powershell
uv run python manage.py makemigrations wearables customers --settings=core.settings.staging
```

Review all generated migration files, constraints and dependencies. Commit them with this backend before deploying. Back up the **staging** database, then apply them there:

```powershell
uv run python manage.py migrate --settings=core.settings.staging
```

Do not use `--run-syncdb`, raw SQL, or manual table creation to bypass migrations. Do not migrate production merely to test this feature.

## 3. Seed the eight test accounts in Aiven staging

From VS Code (configured with the staging DB values):

```powershell
uv run python manage.py seed_direct_login_test_users --confirm-staging --settings=core.settings.staging
uv run python manage.py verify_test_phone_setup --settings=core.settings.staging
```

The seed command outputs each test phone and **customer profile UUID**. Record only the UUID, not any token. It is safe to rerun for the same eight synthetic accounts; it refuses to repurpose a conflicting real/inactive user.

| Account | Phone |
|---|---|
| 01 | `+919999900101` |
| 02 | `+919999900102` |
| 03 | `+919999900103` |
| 04 | `+919999900104` |
| 05 | `+919999900105` |
| 06 | `+919999900106` |
| 07 | `+919999900107` |
| 08 | `+919999900108` |

The seeder uses the backend's canonical phone format (`+91-9999900101`), while the API request accepts the compact `+919999900101` form and normalizes it. Rerunning the seed also repairs the compact format used by the earlier script for these synthetic accounts only.

If `verify_test_phone_setup` reports missing `wearables_*` tables, review and apply migrations first. If the customer role/feature is missing, rerun the seed command **only against staging**.

## 4. Configure and deploy the Render staging web service

1. Create or choose a **staging** web service (NOT the real client-facing service). Use the updated repo/branch containing the reviewed migrations.
2. Under **Environment**, set `DJANGO_SETTINGS_MODULE=core.settings.staging` and use the same relevant `STG_*`, Django `SECRET_KEY`, email/S3 and Aiven settings as in Step 1. **Never** paste your actual key or DB password into repository files, Bruno collections, screenshots, or chat.
3. Keep your existing working build/start commands. For a Render Python service that uses this repo's uv environment, a typical setup is **build** `uv sync --frozen` and **start** `uv run gunicorn core.wsgi:application --bind 0.0.0.0:$PORT`. If Render is Docker-based, preserve the project's Docker build/start procedure and ensure staging settings are injected. Python runtime must satisfy >=3.14.
4. Deploy after migrations have been generated/reviewed and applied. Confirm Render service logs show Gunicorn started and bound to the expected port.
5. If you cannot open Render Shell on your plan, seed and verify from **VS Code connected to that same dedicated Aiven staging database** as in Step 3. No Render Shell is necessary for those commands.

**Security check:** The Render production service must use `core.settings.production` and have no staging test keys, with normal OTP-based login. Direct login returns 404 there even if someone mistakenly sets its flag.

## 5. Smoke-test deployed APIs using VS Code PowerShell

Use **your actual staging Render URL** without a trailing slash:

```powershell
$base = "https://YOUR-STAGING-SERVICE.onrender.com"
$key = $env:STG_TEST_PHONE_LOGIN_KEY
# If your key is in .env instead of PowerShell env, set $key privately before testing.
$login = Invoke-RestMethod -Uri "$base/auth/login-phone-direct/" `
  -Method Post -ContentType "application/json" `
  -Headers @{ "X-Test-Login-Key" = $key } `
  -Body '{"phone":"+919999900101"}'
$access = $login.data.access
$headers = @{ "Authorization" = "Bearer $access" }

Invoke-RestMethod -Uri "$base/devices/" -Method Get -Headers $headers
Invoke-RestMethod -Uri "$base/health/dashboard/" -Method Get -Headers $headers
Invoke-RestMethod -Uri "$base/health/sleep/?days=90" -Method Get -Headers $headers
Invoke-RestMethod -Uri "$base/health/timeline/" -Method Get -Headers $headers
```

If you need the profile explicitly, add `"X-Customer-Profile-ID" = "<profile-UUID-printed-by-seed>"` to `$headers`. Normally it is not needed because the main profile is selected automatically. Send only the **access token** to protected endpoints; never send the `refresh` token as Bearer. Do not print, commit, or share tokens.

**Bruno:** Select `Staging-Test`, edit `baseURL` to your staging service, set the secret environment variable `test_login_key` to your Render `STG_TEST_PHONE_LOGIN_KEY`, run **Auth > Login Phone Direct** then **devices > GET Devices** and **health > GET Domain**. The login Bruno request will save the JWT for subsequent calls.

## 6. Real ROOK connection and data are separate from simple GET success

First `GET /devices/` may legitimately return `connections: []`; `/health/sleep/` may return a **no-data state**. These are successful API responses, not a failure, until the user connects a provider and data is ingested.

To test the *full* ROOK data lifecycle:

1. Have approved sandbox ROOK server/SDK credentials on Render, not only feature flags.
2. Use `POST /devices/connect/` with a supported `data_source`, `consent_accepted: true`, plus any required parameters. Follow the returned external provider authorization URL (or approved mobile SDK flow).
3. Register your deployed `/webhooks/rook/data/` and `/webhooks/rook/notification/` endpoints in the ROOK sandbox portal. Leave unsigned webhooks disallowed.
4. Process enqueued health jobs on a scheduled/worker process (or explicitly run the management command while connected to the staging database):

```powershell
uv run python manage.py process_health_jobs --limit 50 --settings=core.settings.staging
```

5. Retest `GET /devices/`, `GET /health/dashboard/`, `GET /health/sleep/`, and `GET /health/timeline/`. Availability of measurements depends on the connected ROOK source actually delivering those metrics.

If your Render plan doesn't provide a background worker, periodic processing still needs to be scheduled separately; deploying the web server alone will not continuously process pending jobs.

## 7. What errors mean after these changes

| HTTP status | Meaning / action |
|---|---|
| `404` on `/auth/login-phone-direct/` | Staging-only test flag/key not enabled correctly or running production settings. |
| `403` on direct login | Missing/incorrect `X-Test-Login-Key`. |
| `400` on direct login | Phone isn't allowlisted or the synthetic account wasn't seeded with customer role/main profile. |
| `401` on `/devices/` or `/health/*` | Missing/expired/invalid **access** JWT; use `Authorization: Bearer <access>`. Keep the same `SECRET_KEY` across restart/deployments. |
| `403` on `/devices/` or `/health/*` | User's `UserAccount.account_type` isn't `customer`, e.g. an associate/admin token. Log in as one of the synthetic customers. |
| `404` on `/devices/` or `/health/*` | Global or per-profile wearable flag disabled, profile inaccessible/missing, or feature `wearables` not enabled. |
| `500` with missing relation/table | Migrations for `wearables` or other referenced tables are missing. |
| `503` during `/devices/connect/` | ROOK service credentials/configuration missing or unreachable. |

Customer-only tokens **must not** be able to call associate/admin-only APIs. Many unrelated app APIs additionally require seeded centers, appointments, programs, valid linked entities or other role-specific test data. This patch does not fabricate that business data or disable any authorization.

## 8. Testing and limitation

The test module `accounts/verifications/test_direct_login_testing.py` covers production deny, staging deny, wrong/weak key deny, authorized view dispatch, and the eight-number allowlist. With a complete **Python 3.14 Django environment**, you can run:

```powershell
uv run python manage.py test accounts.verifications.test_direct_login_testing --settings=core.settings.staging
```

This package was syntax/structure checked without connecting to Aiven or Render. Live DB migrations, real JWT flows and ROOK provider integration must be validated in your own authorized staging environment. Do not claim every endpoint works until those checks pass.

## 9. Remove the bypass after testing

Disable `STG_TEST_PHONE_LOGIN_ENABLED`, delete the staging key, rotate it if exposed, and stop using `/auth/login-phone-direct/`. The real mobile app should always follow `/auth/request-otp/` then `/auth/login-otp/` and use `/auth/refresh/` for tokens.
