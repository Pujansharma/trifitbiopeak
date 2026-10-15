# Biopeak Nexus ROOK — Development credentials setup (VS Code, Aiven DEV, Render)

This guide is specifically for the **development** Aiven database and the **ROOK sandbox/development** account. It supplements the existing detailed integration guide in this ZIP. No private credential values are embedded. **Never point these commands at client production data.**

## 1. Open and install (VS Code PowerShell)

Extract this ZIP. Open `Biopeak-Nexus-BE` (the folder containing `manage.py`). In VS Code Terminal (PowerShell):

```powershell
uv --version
uv python install 3.14
uv sync --frozen --python 3.14
```

If `uv` is unavailable, follow the official installation instructions at https://docs.astral.sh/uv/getting-started/installation/ .

## 2. Use your existing development `.env` credentials

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

Edit `.env`. **Fill the placeholders with your existing private DEV credential values**; do not replace working environment variables with placeholders. `SECRET_KEY` is already required by the project; retain a stable value, and keep it secret.

```dotenv
DJANGO_SETTINGS_MODULE=core.settings.development
SECRET_KEY=<your existing development Django secret>

# Your development Aiven PostgreSQL database (must NOT be production)
DEV_DB_NAME=<Aiven development database name>
DEV_DB_USER=<Aiven development database user>
DEV_DB_PASSWORD=<Aiven development database password>
DEV_DB_HOST=<Aiven development database host>
DEV_DB_PORT=<Aiven development database port>

# Health API flags
DEV_WEARABLES_ENABLED=True
DEV_WEARABLES_REQUIRE_PROFILE_FEATURE=True
DEV_TIMELINE_ENABLED=True
DEV_RECOVERY_DOMAIN_ENABLED=True
DEV_BODY_DOMAIN_ENABLED=True

# ROOK sandbox/development server credentials
DEV_ROOK_ENVIRONMENT=sandbox
DEV_ROOK_BASE_URL=https://api.rook-connect.review
DEV_ROOK_CLIENT_UUID=<your ROOK dev/sandbox client UUID>
DEV_ROOK_SECRET_KEY=<your ROOK dev/sandbox server secret>
DEV_ROOK_WEBHOOK_HASH_KEY=<your ROOK dev/sandbox webhook signing key>
DEV_ROOK_ALLOW_UNSIGNED_WEBHOOKS=False

# Restricted login for eight synthetic accounts (DEV ONLY)
DEV_TEST_PHONE_LOGIN_ENABLED=True
DEV_TEST_PHONE_LOGIN_KEY=<random private key of at least 32 characters>
```

The ROOK server secret and webhook signing key are separate values. Keep all secrets out of Git and screenshots. You may leave ROOK provider credentials empty until you are ready to connect a source; only schema/empty-state testing will work until they are configured.

Generate a new, strong direct-login key only if you do not have one already:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

`core/settings/development.py` currently sets PostgreSQL `sslmode` to `prefer`; this attempts TLS when supported. For a stricter security posture with Aiven, have the project owner change this fixed setting to `require` and review any certificate verification policy. The existing development configuration does not read a `DEV_DB_SSLMODE` environment variable.

## 3. Verify the connected database before migrations

```powershell
uv run python manage.py check --settings=core.settings.development
uv run python manage.py shell --settings=core.settings.development -c "from django.db import connection; print('Database:', connection.settings_dict['NAME'])"
uv run python manage.py showmigrations wearables --settings=core.settings.development
uv run python manage.py showmigrations customers --settings=core.settings.development
```

Stop if the database name is not your intended **development** database. The previous full ROOK source ZIP contains the `wearables/migrations/__init__.py` initializer, but not a generated initial ROOK migration.

## 4. Create/review/apply the ROOK schema (migration files owned by the project)

```powershell
uv run python manage.py makemigrations wearables --settings=core.settings.development
uv run python manage.py migrate --plan --settings=core.settings.development
```

Review all newly generated migrations and the complete plan, especially any operations outside `wearables`, with the project's migration owner. Only if the plan is safe and the development Aiven database has a backup:

```powershell
uv run python manage.py migrate --settings=core.settings.development
uv run python manage.py showmigrations wearables --settings=core.settings.development
uv run python manage.py verify_rook_setup --settings=core.settings.development
```

Expected: `[X]` for the new wearable initial migration, and all wearable tables present. ROOK documents, measurements, and jobs can still be empty. If the plan reports missing or inconsistent `customers` migrations, stop, review, and generate the necessary customer migration separately rather than blindly migrating unrelated apps. Do not run `--run-syncdb` or hand-create the tables.

**Important:** `verify_rook_setup` in this source version has a few hardcoded `STG_*` messages. When running with `--settings=core.settings.development`, replace that prefix **in the error guidance only** with `DEV_*`; the actual runtime check correctly reads your loaded Django settings.

## 5. Create eight test customers (using DEV settings, no `--confirm-staging`)

```powershell
uv run python manage.py seed_direct_login_test_users --settings=core.settings.development
uv run python manage.py verify_test_phone_setup --settings=core.settings.development
```

The numbers are `+919999900101` through `+919999900108`; the database stores a normalized `+91-...` representation. The seeder creates customer records, main customer profiles and wearable feature access. It requires `DEV_TEST_PHONE_LOGIN_ENABLED=True` and a key at least 32 characters long. **Do not seed a real client database.**

## 6. Start Django and authenticate locally

```powershell
uv run python manage.py runserver 127.0.0.1:8000 --settings=core.settings.development
```

Open Swagger at `http://127.0.0.1:8000/openapi/docs/`. In another PowerShell terminal:

```powershell
$baseUrl = 'http://127.0.0.1:8000'
$testKey = Read-Host 'DEV test login key'
$login = Invoke-RestMethod -Uri "$baseUrl/auth/login-phone-direct/" -Method Post -Headers @{'X-Test-Login-Key'=$testKey} -ContentType 'application/json' -Body '{"phone":"+919999900101"}'
$authHeaders = @{ Authorization = "Bearer $($login.data.access)" }
Invoke-RestMethod -Uri "$baseUrl/devices/" -Method Get -Headers $authHeaders
Invoke-RestMethod -Uri "$baseUrl/health/dashboard/" -Method Get -Headers $authHeaders
Invoke-RestMethod -Uri "$baseUrl/health/sleep/?days=90" -Method Get -Headers $authHeaders
```

If login yields HTTP 404, confirm the `DEV_TEST_PHONE_LOGIN_*` flags, key length, and development settings. If 403, verify the account is one of the eight authorized synthetic identities and the test key is correct. If protected GETs return 401, use the returned **access** token, not the refresh token. If GETs return 403, check the seeded customer account type; if 404, check feature flags; if database relation missing, apply reviewed migrations.

## 7. Render + the same development credentials (without exposing Django DEBUG)

The existing `core.settings.development` sets `DEBUG=True`, `ALLOWED_HOSTS=['*']`, and permits all CORS origins, so **do not deploy that settings module to a public Render service**.

For a **separate, access-controlled Render test service**, keep `DJANGO_SETTINGS_MODULE=core.settings.staging` (`DEBUG=False`) and assign the **same existing DEV credential values** to the staging setting *names* the deployed module reads:

| Render variable | Value to copy from private development credentials |
| --- | --- |
| `STG_DB_NAME` | value of `DEV_DB_NAME` |
| `STG_DB_USER` | value of `DEV_DB_USER` |
| `STG_DB_PASSWORD` | value of `DEV_DB_PASSWORD` |
| `STG_DB_HOST` | value of `DEV_DB_HOST` |
| `STG_DB_PORT` | value of `DEV_DB_PORT` |
| `STG_DB_SSLMODE` | `require` |
| `STG_ROOK_ENVIRONMENT` | value of `DEV_ROOK_ENVIRONMENT` (`sandbox`) |
| `STG_ROOK_BASE_URL` | value of `DEV_ROOK_BASE_URL` |
| `STG_ROOK_CLIENT_UUID` | value of `DEV_ROOK_CLIENT_UUID` |
| `STG_ROOK_SECRET_KEY` | value of `DEV_ROOK_SECRET_KEY` |
| `STG_ROOK_WEBHOOK_HASH_KEY` | value of `DEV_ROOK_WEBHOOK_HASH_KEY` |
| `STG_TEST_PHONE_LOGIN_KEY` | value of `DEV_TEST_PHONE_LOGIN_KEY` |

Also set these nonsecret staging flags for the Render service:

```dotenv
STG_WEARABLES_ENABLED=True
STG_WEARABLES_REQUIRE_PROFILE_FEATURE=True
STG_TIMELINE_ENABLED=True
STG_TEST_PHONE_LOGIN_ENABLED=True
STG_ROOK_ALLOW_UNSIGNED_WEBHOOKS=False
```

This is **still your development Aiven database and ROOK sandbox**, not separate staging credentials. The variable prefixes are required because the existing Django staging module reads `STG_*` names. Preserve other settings the Render service already requires: staging email settings, S3 settings and an appropriate stable `SECRET_KEY`. Protect the test service with access controls and never attach it to production data.

Deploy the source and **reviewed generated migration files**. Do not regenerate migrations on Render. Use a stable HTTPS Render URL for ROOK's signed data webhook:

`https://YOUR-TEST-RENDER-SERVICE.onrender.com/webhooks/rook/data/`

Optionally configure the ROOK notification webhook:

`https://YOUR-TEST-RENDER-SERVICE.onrender.com/webhooks/rook/notification/`

Configure the signature key in ROOK Sandbox Portal to match the Render value. ROOK cannot reach your localhost without a secure public forwarding tunnel. The application only accepts signed webhooks by default. Protect the Render testing shortcut; the header key must never be embedded in the published mobile client.

## 8. Connect a source and process ROOK health documents

With a valid customer access token, call `POST /devices/connect/` with e.g.:

```json
{
  "data_source": "Fitbit",
  "consent_accepted": true,
  "consent_version": "v1",
  "historical_days": 29,
  "timezone_name": "Asia/Kolkata"
}
```

Open the returned authorization URL and authorize a test provider account. For sandbox data without a wearable, use the ROOK Portal JSON simulator with the **same** `rookUserId` and signed delivery. Check `GET /devices/?refresh=true`, webhook HTTP `202`, and database job/document counts.

A webhook `202` means processing **queued**, not completed. Run on the worker/terminal connected to the **same dev Aiven database**:

```powershell
uv run python manage.py process_health_jobs --limit 50 --settings=core.settings.development
uv run python manage.py verify_rook_setup --require-provider --settings=core.settings.development
```

Refresh `/health/dashboard/`, `/health/sleep/?days=90`, `/health/activity/`, `/health/heart/`, `/health/body/`, `/health/recovery/`, and `/health/timeline/`. Schedule repeated execution of `process_health_jobs` and daily `enqueue_health_freshness_checks` for ongoing ingestion, using the same dev DB and configuration in every worker process.

Native Apple Health and Health Connect require a mobile SDK/app integration, not just Django APIs. No real readings will appear until provider consent and valid data delivery occur.

## Summary of settings selection

- **VS Code local:** `core.settings.development`, `DEV_*`, use `--settings=core.settings.development` on every command.
- **Aiven:** Your existing dedicated **development** PostgreSQL database.
- **ROOK:** Your existing **sandbox/development** ROOK credentials.
- **Public Render test service:** Safer `core.settings.staging` with the **same dev values mapped to `STG_*` names**, not public `core.settings.development`.
- **Never use** client production data, disable ROOK webhook signature verification on public URLs, or publish test-login secrets.

The code package was syntax/smoke tested offline previously; live Aiven migration and ROOK provider/webhook behavior must be verified in your environment.
