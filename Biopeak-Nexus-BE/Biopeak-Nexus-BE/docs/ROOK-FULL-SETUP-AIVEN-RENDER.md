# Biopeak Nexus ROOK — Windows VS Code → Aiven staging → Render staging → ROOK sandbox

This guide accompanies the updated **staging** test backend. It covers **both** database schema creation and the *existing* ROOK source → webhook → processing job → health API pipeline. Read it once, then run the numbered commands in order. A separate Aiven staging database is mandatory: do not run these commands against a client production database.

## Scope, remaining dependencies, and changes

The backend already has 10 Django ROOK models, `/devices/`, `/health/*`, `/webhooks/rook/data/`, `/webhooks/rook/notification/`, `process_health_jobs`, and `enqueue_health_freshness_checks`. This package corrects the ROOK provider-revoke route to `/data_sources/revoke_auth`, adds an explicit User-Agent required by current ROOK WAF guidance, and validates webhook HMAC using a nested `metadata.datetime_string` (with legacy notification fallback). It adds `verify_rook_setup`, related source tests, and the migration package initializer.

**Migration caution:** This source bundle intentionally contains **no generated `wearables/migrations/0001_initial.py`**. Django 6 and Python 3.14 are needed to generate one reliably from the actual models and verify cross-app dependencies. The migration has **not** been applied to Aiven by the package author. Do not hand-create SQL tables or run `--run-syncdb`.

**External prerequisites:** You need authorized ROOK **Sandbox** client UUID, server secret, webhook HMAC signing key, a configured sandbox ROOK Portal, Render staging URL, and (for actual readings) a linked provider account or native mobile SDK. The backend alone cannot obtain real device measurements without consent and ROOK deliveries. Native Apple Health/Health Connect/Samsung Health require mobile-client SDK work.

## 1. Extract and install — PowerShell in VS Code

1. Extract the ZIP and use File → Open Folder on **`Biopeak-Nexus-BE`**, where `manage.py` exists.
2. Open Terminal → New Terminal (PowerShell).
3. Verify `uv` and Python version; project `pyproject.toml` requires **Python >=3.14**.

```powershell
uv --version
uv python install 3.14
uv python find 3.14
uv sync --frozen --python 3.14
```

If `uv` is not installed, install it using the official uv instructions at https://docs.astral.sh/uv/getting-started/installation/ . If an installation command fails, stop at that error; do not continue to migrations with missing dependencies.

## 2. Configure an isolated Aiven/Render *staging* environment

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Open `.env` in VS Code. Set values below, replacing placeholders with your **staging** values. `core.settings.staging` reads `STG_DB_*` separately, **not** `DATABASE_URL`. Do not commit `.env` or copy secrets into chats.

```dotenv
DJANGO_SETTINGS_MODULE=core.settings.staging
SECRET_KEY=<your staging Django signing key>
STG_DB_NAME=<separate Aiven test database>
STG_DB_USER=<Aiven test database user>
STG_DB_PASSWORD=<Aiven password>
STG_DB_HOST=<Aiven host>
STG_DB_PORT=<Aiven port>
STG_DB_SSLMODE=require

STG_WEARABLES_ENABLED=True
STG_WEARABLES_REQUIRE_PROFILE_FEATURE=True
STG_TIMELINE_ENABLED=True
STG_ROOK_ENVIRONMENT=sandbox
STG_ROOK_BASE_URL=https://api.rook-connect.review
STG_ROOK_CLIENT_UUID=<ROOK Sandbox client UUID>
STG_ROOK_SECRET_KEY=<ROOK Sandbox server secret>
STG_ROOK_WEBHOOK_HASH_KEY=<ROOK Sandbox webhook signing key>
STG_ROOK_ALLOW_UNSIGNED_WEBHOOKS=False

# Optional: ONLY if using the eight isolated test accounts:
STG_TEST_PHONE_LOGIN_ENABLED=True
STG_TEST_PHONE_LOGIN_KEY=<32+ character random key>

# Required by staging settings on import, even when ROOK alone is in focus:
STG_EMAIL_HOST=<existing staging email host>
STG_EMAIL_PORT=<existing staging email port>
STG_EMAIL_HOST_USER=<existing staging email user>
STG_EMAIL_HOST_PASSWORD=<existing staging email password>
STG_DEFAULT_FROM_EMAIL=<existing staging from-address>
AWS_S3_ACCESS_KEY_ID=<existing staging AWS key>
AWS_S3_SECRET_ACCESS_KEY=<existing staging AWS secret>
AWS_STORAGE_BUCKET_NAME=<existing staging S3 bucket>
AWS_S3_REGION_NAME=<existing staging S3 region>
AWS_S3_CUSTOM_DOMAIN=<existing staging S3 domain>
```

Get the HMAC key separately from ROOK Portal → Setup → Webhook → Signature. This is **not** the same as `STG_ROOK_SECRET_KEY`. If you do not yet have ROOK credentials, leave those values empty and **only perform DB/empty-state testing**; `POST /devices/connect/` for API-based sources will return a configuration error until they are set.

To generate a strong test-login key, run locally and save the output only to `.env` and your private Render staging environment:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Keep Django `SECRET_KEY` stable across local staging and Render for token validation. Keep staging isolated from production.

## 3. Check the project before touching tables

Run from the backend folder:

```powershell
uv run python manage.py check --settings=core.settings.staging
uv run python manage.py showmigrations customers --settings=core.settings.staging
uv run python manage.py showmigrations wearables --settings=core.settings.staging
```

`showmigrations wearables` may show no listed migrations at first; that's expected before the new initial migration is generated. If the database connection fails, fix Aiven IP allowlisting/firewall, host/port, user/password, SSL mode and database selection first.

## 4. Create and apply ROOK schema migrations **once**

In the **source working copy**, generate migrations only for the new ROOK app and the relevant customer app (which can have pending changes). Do not blindly create migrations for unrelated apps.

```powershell
uv run python manage.py makemigrations wearables customers --settings=core.settings.staging
```

Check that `wearables/migrations/0001_initial.py` is created, and review all generated files/foreign key dependencies, indexes, and other pending operations. Commit **reviewed** migration files with the backend code so local and Render share the same schema. For a shared Aiven DB, ensure its existing migration history is compatible; have the project migration owner review conflicts.

```powershell
uv run python manage.py migrate --plan --settings=core.settings.staging
```

**Stop if the plan contains surprising deletes, unrelated operations, or migration conflicts.** Take an Aiven staging database backup/snapshot before applying any changes. Once reviewed:

```powershell
uv run python manage.py migrate --settings=core.settings.staging
uv run python manage.py showmigrations wearables --settings=core.settings.staging
uv run python manage.py verify_rook_setup --settings=core.settings.staging
```

Expected: `[X] 0001_initial` (or your reviewed next migration), and the preflight says all 10 ROOK model tables exist. An empty documents/observations count is normal at this stage. The **generated migration must be included in your Render deployment branch**. Do not run `makemigrations` on a live Render service.

## 5. Seed and verify eight test customer accounts (staging only)

```powershell
uv run python manage.py seed_direct_login_test_users --confirm-staging --settings=core.settings.staging
uv run python manage.py verify_test_phone_setup --settings=core.settings.staging
```

This creates synthetic customer account role/profile/feature records in the configured Aiven staging DB. The eight phone numbers are `+919999900101` through `+919999900108` (sent to the API compactly); the database may store them in the normalized `+91-9999900101` format. Use the seeder output to identify customer profiles. **Never seed a production database**.

## 6. Run the backend locally (same Aiven staging database)

```powershell
uv run python manage.py runserver 127.0.0.1:8000 --settings=core.settings.staging
```

Open `http://127.0.0.1:8000/openapi/docs/` for local Swagger UI. This server uses the staging DB configuration; it does **not** receive external ROOK webhooks because localhost isn't a public HTTPS endpoint. Keep this terminal running and open a **second terminal** for subsequent commands.

## 7. Deploy the exact same branch to Render staging

1. Push the updated source **and reviewed generated migration files** to the branch your separate Render staging service tracks.
2. In Render → Environment, configure the same `DJANGO_SETTINGS_MODULE`, `STG_DB_*`, email/storage, flags and ROOK **sandbox** secrets. Render staging must point at the same Aiven staging database.
3. Keep the existing known-working Render build/start commands; do not switch database environments. If you use the repo Docker image, it expects Python 3.14, the frozen uv lock and `assets/scripts/server.sh`.
4. Deploy. Open Render logs. A successful Gunicorn `Listening at: http://0.0.0.0:10000` proves the process launched, **not** that the ROOK DB/credentials work.
5. Run (locally connected to that same staging DB, or Render Shell if available):

```powershell
uv run python manage.py verify_rook_setup --require-provider --settings=core.settings.staging
```

The preflight checks table existence and whether all server/webhook settings are nonempty; it cannot prove your secret is accepted by ROOK. `STG_WEARABLES_REQUIRE_PROFILE_FEATURE=True` additionally requires each target customer profile to have `wearables` enabled, which the eight-account seed does.

## 8. Login and test the existing backend APIs

Use PowerShell in a **second terminal**; set your actual Render staging host and keep the test key secret:

```powershell
$baseUrl = "https://YOUR-STAGING-SERVICE.onrender.com"
$testKey = Read-Host "Staging test login key"
$login = Invoke-RestMethod -Uri "$baseUrl/auth/login-phone-direct/" -Method Post -Headers @{"X-Test-Login-Key"=$testKey} -ContentType "application/json" -Body '{"phone":"+919999900101"}'
$token = $login.data.access
$authHeaders = @{ Authorization = "Bearer $token" }
Invoke-RestMethod -Uri "$baseUrl/devices/" -Method Get -Headers $authHeaders
Invoke-RestMethod -Uri "$baseUrl/health/dashboard/" -Method Get -Headers $authHeaders
Invoke-RestMethod -Uri "$baseUrl/health/sleep/?days=90" -Method Get -Headers $authHeaders
Invoke-RestMethod -Uri "$baseUrl/health/timeline/" -Method Get -Headers $authHeaders
```

**Do not print or share JWTs.** If 401, ensure `$login.data.access` exists and `Authorization: Bearer ...` is sent; if 403, check the seeded account role; if 404, check `STG_WEARABLES_ENABLED` and profile feature. If DB reports `relation does not exist`, the migration was not applied to the database used by Render. Empty health results are expected without ROOK data.

## 9. Connect an API source (e.g. Fitbit) and receive real ROOK data

1. Log into the **ROOK Sandbox Portal** (not Production). Confirm the client UUID and secret correspond to that environment.
2. In ROOK Portal → Setup → Webhook, enter **Data Webhook** URL:

   `https://YOUR-STAGING-SERVICE.onrender.com/webhooks/rook/data/`

   If enabled in your ROOK plan, enter **Notification Webhook** URL:

   `https://YOUR-STAGING-SERVICE.onrender.com/webhooks/rook/notification/`

   Configure HMAC signature signing key in ROOK Portal; use the same private value as `STG_ROOK_WEBHOOK_HASH_KEY`. Keep `STG_ROOK_ALLOW_UNSIGNED_WEBHOOKS=False`. Do not use webhook Basic Auth unless you also implement matching backend auth (this package verifies the ROOK signature, not HTTP Basic Auth).
3. Start a connection for one authorized **synthetic test customer**:

```powershell
$connectBody = @{
  data_source = "Fitbit"
  consent_accepted = $true
  consent_version = "v1"
  historical_days = 29
  timezone_name = "Asia/Kolkata"
} | ConvertTo-Json
$connect = Invoke-RestMethod -Uri "$baseUrl/devices/connect/" -Method Post -Headers $authHeaders -ContentType "application/json" -Body $connectBody
$rookUserId = $connect.data.rookUserId
$connect.data.authorizationUrl
```

4. Open the returned authorization URL in the browser and consent in the Fitbit/provider sandbox test account. Do not put your ROOK server secret into your mobile frontend.
5. Refresh status and inspect the connection:

```powershell
Invoke-RestMethod -Uri "$baseUrl/devices/?refresh=true" -Method Get -Headers $authHeaders
```

6. Once ROOK sends a **signed** document for **the same `rookUserId`**, Render webhook logs should show HTTP **202** and the Aiven ROOK document/processing job counts should increase. If using ROOK Portal → Tools → JSON Simulator, ensure the simulated `user_id` is your backend's `rookUserId` (many ROOK simulator samples use a generic user ID; unknown users are intentionally ignored). Test the portal's webhook delivery result; don't fake or bypass the signature on a public environment.

## 10. Process health records (not automatic unless scheduled)

Receiving a 202 only **queues** a normalization job. Run the existing management command (on Render Shell or a locally connected, correctly configured worker):

```powershell
uv run python manage.py process_health_jobs --limit 50 --settings=core.settings.staging
uv run python manage.py verify_rook_setup --require-provider --settings=core.settings.staging
```

Then retry `GET /health/dashboard/`, `/health/sleep/`, `/health/activity/`, `/health/body/`, `/health/heart/`, `/health/recovery/`, `/health/workouts/`, and `/health/timeline/`. Domain states reflect available metrics; not every ROOK payload contains each metric.

For ongoing delivery **configure a scheduled worker/Render Cron Job or separate background worker** to execute `process_health_jobs` frequently (e.g. every 1–5 minutes, subject to your deployment platform's supported schedule). Independently schedule daily maintenance:

```powershell
uv run python manage.py enqueue_health_freshness_checks --settings=core.settings.staging
uv run python manage.py process_health_jobs --limit 50 --settings=core.settings.staging
```

The worker must share the **same Aiven DB and ROOK staging settings** as the web service. Without a recurring worker, incoming data will queue but dashboards might remain empty. Render free web services may spin down; use an always-on deployment for dependable live webhooks. Use the existing `assets/scripts/sweep_jobs.sh` only if the other appointment and communications sweeps are also intended to run.

## 11. Native Apple Health / Health Connect / Samsung Health

These providers cannot be connected through a backend-only OAuth URL. The mobile app must integrate the proper ROOK SDK (or ROOK App) and obtain user consent. Your backend already exposes the workflow: `POST /devices/connect/`, `GET /devices/sdk-config/`, `POST /devices/native-status/`, then signed ROOK webhooks and background jobs. Add the **separate** SDK credentials (`STG_ROOK_SDK_CLIENT_UUID`, `STG_ROOK_SDK_SECRET`) only when implementing this client-side feature. The backend release is not a substitute for the mobile SDK.

## 12. Run tests and avoid preventable issues

Use a **disposable local test database** (not client production/Aiven production) for any Django tests that create/drop test DBs. With that database configured:

```powershell
uv run python manage.py check --settings=core.settings.development
uv run python manage.py test wearables.tests --settings=core.settings.development
```

For source-level-only authentication/ROOK contract tests:

```powershell
uv run python manage.py test wearables.tests.test_client wearables.tests.test_signature accounts.verifications.test_direct_login_testing --settings=core.settings.development
```

ROOK API/WAF 403 → verify configured sandbox base URL, API credentials, and outgoing User-Agent. Webhook 403 → HMAC mismatch / wrong environment key / wrong `metadata.datetime_string`. Webhook 202 but no metrics → check document user ID, migration tables, queued jobs, actual measurement fields. API 503 on connect → credentials not configured. ROOK API 401 → sandbox/production credentials mixed. DB missing-table errors → generate/review/apply migrations to correct staging DB. Render restart or spin-down does not automatically process the health jobs.

**Final verification means** migration marked `[X]`, preflight passing, one authorized connection, signed webhook delivering 202 for the correct `rookUserId`, queued job processed successfully, and stored observations visible via JWT-protected health APIs. Neither syntax checks nor this guide prove the full external ROOK integration without your credentials and a real/simulated accepted delivery.

Official ROOK references: https://docs.tryrook.io/docs/rookconnect/quickstart/ ; https://docs.tryrook.io/docs/rookconnect/data_delivery/ ; https://support.tryrook.io/en/articles/16875516-how-do-i-set-up-webhooks-in-the-rook-portal ; https://docs.tryrook.io/api/ .
