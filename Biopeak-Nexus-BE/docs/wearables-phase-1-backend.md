# Wearables Phase 1 Backend Integration

## Status

Phase 1 backend implementation exists as an additive Django/PostgreSQL module. Production readiness and live integration remain subject to the gates in [PHASE1_PRD_IMPLEMENTATION_STATUS.md](PHASE1_PRD_IMPLEMENTATION_STATUS.md). The implementation uses only the new Biopeak API names. No `/wearable/*` compatibility aliases are registered.

This phase includes:

- Biopeak JWT and `CustomerProfile` ownership.
- Profile-level ROOK identity.
- Wearable consent audit records.
- API-based and native SDK connection states.
- ROOK authorizer, status refresh, and source revocation.
- Signed data and notification webhooks.
- Strict document-version and replay handling.
- Raw ROOK documents plus canonical observations.
- Daily summaries, trend inputs, confidence, completeness, and freshness.
- Six fixed dashboard domains.
- Domain detail and provider-independent timeline APIs.
- Durable retryable processing and recovery jobs.
- History-preserving disconnect/reconnect behavior.
- Per-profile rollout through the existing profile feature model.

## ROOK Authorization Callback (Optional)

ROOK's authorizer accepts an HTTPS `redirect_url` of at most **50 characters**, and appends
`/client_uuid/<client_uuid>/user_id/<rook_user_id>` to the URL path. To enable Biopeak's
one-time nonce check, configure `DEV_ROOK_CALLBACK_URL`, `STG_ROOK_CALLBACK_URL`, or
`PRD_ROOK_CALLBACK_URL` as a *short base URL ending in `/r`*, e.g.
`https://api.example.org/r` (real host must be accessible over HTTPS).
The backend appends a fresh random path component under that limit, checks both ROOK
path identifiers, and confirms authorization using ROOK's authenticated API. The
public callback is `GET /r/<state_token>/client_uuid/<client_uuid>/user_id/<rook_user_id>`.
The client should refresh `GET /devices/?refresh=true` after returning to the app.
If no callback base is configured, direct provider status polling still works; do
not pass a redirect longer than 50 characters.

The callback is still pending sandbox end-to-end verification with the configured
ROOK account and provider redirect. Do not treat a browser redirect as proof of
authorization.

## Architecture

ROOK remains the system of acquisition. Biopeak remains the system of record and intelligence.

1. The mobile app authenticates with Biopeak JWT.
2. `X-Customer-Profile-ID` selects the owned customer profile. If omitted, the main profile is used.
3. Biopeak creates a stable alphanumeric ROOK user ID for that profile.
4. API sources use ROOK's authorizer endpoint. Native sources use the mobile SDK.
5. ROOK delivers normalized documents to the signed Biopeak webhook.
6. Biopeak durably stores the document and queues normalization before acknowledging it.
7. Background jobs extract canonical observations, rebuild affected daily summaries, and refresh domain snapshots.
8. Mobile clients query Biopeak only. They never consume a ROOK payload directly.

MongoDB and the test application's separate authentication/session layer are not used.

## Public API Contract

All member endpoints require a Biopeak customer JWT. Responses use Biopeak's `{detail, data}` envelope.

### Devices

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/devices/` | Connections, authorization, permission, import, freshness, errors, and backend-provided actions |
| `POST` | `/devices/connect/` | Record consent and initiate API or SDK authorization |
| `POST` | `/devices/disconnect/` | Revoke one provider while retaining all history |
| `POST` | `/devices/retry-sync/` | Request recovery for an API-based ROOK source |
| `GET` | `/devices/sdk-config/` | Return profile-specific ROOK mobile SDK configuration after native connect consent |
| `POST` | `/devices/native-status/` | Record SDK linking, OS permission state, capabilities, and timezone for an initiated native connection |
| `POST` | `/devices/consent/revoke/` | Revoke member consent, disconnect sources, retain historical observations |

`GET /devices/?refresh=true` performs an authoritative ROOK status refresh for API connections still authorizing. Normal device reads stay database-backed.

Example connection request:

```json
{
  "data_source": "Garmin",
  "consent_accepted": true,
  "consent_version": "v1",
  "historical_days": 7,
  "timezone_name": "Asia/Kolkata",
  "preferred_units": "metric"
}
```

Native sources are `Apple Health`, `Health Connect`, and `Samsung Health`. The ROOK authorization API currently documents `Garmin`, `Fitbit`, `Oura`, `Polar`, `Withings`, `Whoop`, and `Dexcom`. `Strava` remains a future option in the source vocabulary but is rejected at connect time until supported by the ROOK authorizer.

### Health

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health/dashboard/` | One response containing all six cards in fixed order |
| `GET` | `/health/{domain}/` | Current value, trend, graph, all available metrics, actions, messages, and metadata |
| `GET` | `/health/timeline/` | Chronological wearable observations plus read-only legacy lab/assessment milestones (global timeline only) |

Valid domains are `sleep`, `activity`, `heart`, `recovery`, `body`, and `workouts`.

Domain detail accepts `?days=1..365`. Timeline filters are `start`, `end`, `domain`, `offset`, and `limit` (maximum 200).

Every card uses the shared schema:

```text
id, title, state, currentValue, trend, graph, actions, messages, metadata
```

The backend returns actions and precomputed graph points. The frontend must not calculate trends, infer provider behavior, replace missing measurements with zero, or manufacture gap values.

### ROOK webhooks

| Method | Route | Purpose |
| --- | --- | --- |
| `POST` | `/webhooks/rook/data/` | Signed ROOK v2 health document delivery |
| `POST` | `/webhooks/rook/notification/` | Connection, disconnection, import, and retrieval notifications |

Production rejects unsigned webhooks. Notifications use `action_datetime` only after verifying the signed payload; confirm this notification variant with actual ROOK deliveries. Validation uses `X-ROOK-HASH` with HMAC-SHA256 over the exact concatenation of `client_uuid`, `user_id`, and nested `metadata.datetime_string` (literal), using the separate ROOK webhook hash key.

Signed ROOK v2 deliveries are accepted as one document per request. Unsigned arrays are allowed only when explicitly enabled for the local sandbox simulator.

## Persistence Model

| Model | Responsibility |
| --- | --- |
| `RookMemberIdentity` | One stable ROOK identity per customer profile, plus timezone and units |
| `WearableConsent` | Consent version, actor, time, IP, user agent, and lifecycle |
| `WearableConnection` | Provider state, authorization, permission, import progress, sync health, and available range |
| `WearableConnectionEvent` | Immutable connection lifecycle audit |
| `RookHealthDocument` | Latest accepted version of each raw ROOK document |
| `RookWebhookReceipt` | Replay/conflict receipt ledger |
| `HealthObservation` | Canonical timestamped metric values with provenance |
| `HealthDailySummary` | Provider-independent daily aggregates used by analytics |
| `HealthDomainSnapshot` | Versioned presentation snapshot for each domain |
| `HealthProcessingJob` | Durable normalization, analytics, status, revocation, freshness, and recovery jobs |

Historical observations are never deleted by disconnect. Raw-data retention must be set by the approved DPDP retention policy before a cleanup command is added.

## Idempotency and Corrections

Document identity is based on profile, ROOK data structure and UTC observation datetime. ROOK document/event identifiers are not included in this correction key.

- Exact payload replay: acknowledged and ignored.
- Lower `document_version`: acknowledged and ignored.
- Same version with different content: recorded as a conflict and ignored.
- Higher version: replaces the current raw document, rebuilds its observations, recomputes the affected daily summary, and refreshes analytics.

This prevents duplicate days and ensures historical corrections affect only the relevant range.

## Deterministic Card States

The API returns only the PRD state vocabulary:

- `loading`
- `historical_import_running`
- `historical_import_partial`
- `historical_import_failed`
- `available`
- `current_value_only`
- `trend_available`
- `waiting_for_data`
- `permission_required`
- `unsupported`
- `no_data`
- `disconnected`
- `provider_error`
- `authorization_expired`
- `sync_delayed`
- `historical_gap`

Cards never disappear. Missing measurements do not become zero. Disconnected cards may still include retained current/history values while their state and action require reconnection.

## Analytics Rules

- Current value requires at least one valid observation.
- The graph is based on canonical daily summaries.
- A short trend requires the configurable minimum observation count (default seven days).
- The `7d` view requires 7 observed days, `30d` requires 21, and `90d` requires 60. Each card returns these decisions in `graph.windowAvailability` so the frontend does not infer them.
- Direction compares the latest seven-day mean against the prior available window, up to 28 days.
- Minimum meaningful change is metric-specific and versioned in the backend.
- Missing days reduce completeness and confidence.
- Low confidence suppresses improving/declining interpretation.
- No interpolation is performed.
- The algorithm version is stored and returned as `wearables-v1.0`.

The provisional minimum-meaningful-change values must receive clinical approval before production interpretation is enabled. The implementation defaults to conservative confidence gating.

## Background Jobs

`process_health_jobs` handles independently retryable jobs:

- `normalize_document`
- `refresh_analytics`
- `refresh_connection`
- `revoke_connection`
- `recovery_pull`
- `freshness_check`

`enqueue_health_freshness_checks` queues active-profile snapshot checks and seven-day ROOK API recovery pulls for API connections that are missing or have delayed synchronization.

Both commands are included in `assets/scripts/sweep_jobs.sh`. Webhooks remain the primary delivery mechanism; recovery pulls are a fallback.

## Feature Flags

Environment switches control the module globally. The existing `CustomerProfileFeature.enabled_tabs` also supports a `wearables` value for member-level rollout when `*_WEARABLES_REQUIRE_PROFILE_FEATURE=True`.

Production defaults `WEARABLES_ENABLED` and `TIMELINE_ENABLED` to false. Enable them only after migrations, ROOK portal configuration, monitoring, and rollout approval.

## Required Environment Variables

Each environment uses its existing prefix (`DEV_`, `STG_`, or `PRD_`):

```text
WEARABLES_ENABLED
WEARABLES_REQUIRE_PROFILE_FEATURE
TIMELINE_ENABLED
RECOVERY_DOMAIN_ENABLED
BODY_DOMAIN_ENABLED
ROOK_ENVIRONMENT
ROOK_BASE_URL
ROOK_CLIENT_UUID
ROOK_SECRET_KEY
ROOK_WEBHOOK_HASH_KEY
ROOK_SDK_CLIENT_UUID
ROOK_SDK_SECRET
ROOK_HISTORICAL_DAYS
ROOK_SYNC_DELAY_HOURS
ROOK_CONNECT_TIMEOUT_SECONDS
ROOK_READ_TIMEOUT_SECONDS
ROOK_AUTHORIZATION_ALLOWED_HOSTS
HEALTH_TREND_MINIMUM_OBSERVATIONS
HEALTH_HISTORICAL_GAP_DAYS
```

`ROOK_SECRET_KEY` is the server Basic-auth secret. `ROOK_SDK_SECRET` is the credential required by the mobile SDK. They must be configured separately; the API credential must not be exposed as a mobile SDK credential.

`ROOK_AUTHORIZATION_ALLOWED_HOSTS` is a comma-separated allowlist for non-Garmin provider authorization URLs. Garmin is always restricted to `connect.garmin.com`. Populate the allowlist from the provider URLs returned in the approved ROOK environment before enabling other API providers.

`ROOK_ALLOW_UNSIGNED_WEBHOOKS` exists only for development sandbox simulation. It is hard-disabled in production.

## Deployment Checklist

The repository rule prohibits agents from generating migrations. Before running the integration:

1. Review the models and approved retention policy.
2. Run `uv run python manage.py makemigrations wearables customers`.
3. Review the generated migrations and index/constraint names.
4. Run migrations in the deployment environment.
5. Configure the production ROOK data webhook URL.
6. Ask ROOK to enable/configure the notification webhook.
7. Add server, SDK, and HMAC credentials to the deployment secret store.
8. Integrate the mobile ROOK SDK for native sources.
9. Run `uv run python manage.py process_health_jobs` through the scheduled worker.
10. Enable the global feature flags and then the `wearables` profile tab for the approved cohort.

## Validation Commands

```bash
uv run ruff check wearables webhooks/rook
uv run python manage.py check
uv run python manage.py test wearables
```

Database-backed tests require PostgreSQL plus the generated migrations. Pure metric, provenance, URL-safety, and signature tests run without a database.

## External Gates Before Production

Code completion does not resolve these external dependencies:

- Production ROOK credentials and dedicated HMAC key.
- Portal data-webhook configuration.
- Notification-webhook activation by ROOK.
- Provider provisioning for sources requiring developer accounts.
- Mobile SDK implementation and permission UX.
- Approved DPDP consent, retention, account-deletion, and residency policies.
- Clinical approval of trend thresholds and interpretation copy.
- Production alert routing and support ownership.


## Release audit caveats (October 2026)

- These endpoints are newly added; client OTP, profile, appointment and other existing
  APIs come from the client-original ZIP, not the separately edited updated ZIP.
- The ROOK nested metadata timestamp and plural revoke endpoint match the current
  official published API, but require real sandbox payload validation before launch.
- A short, hashed one-time OAuth callback state is implemented; **the actual ROOK
  provider redirect and live identity checks remain untested**. Polling remains supported.
- The health timeline now reads existing `ServiceResult` assessment/lab milestones and
  completed diagnostic-order report availability via profile-scoped, read-only queries.
  Dates reflect existing record timestamps; clinical report values are not included.
  Source queries still need live database validation and product approval.
- No live PostgreSQL, ROOK, or mobile SDK tests are represented as passed.
- Deploy with production wearable feature flags OFF until database migrations, a shared cache (LocMem is currently per-process),
  ROOK HMAC checks, scheduler setup, regression tests and mobile E2E checks pass.
