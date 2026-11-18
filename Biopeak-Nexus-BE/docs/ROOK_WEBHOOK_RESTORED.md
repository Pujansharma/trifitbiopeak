# ROOK Data Webhook — Existing Tables Only

Updated: 18 November 2026. Source: uploaded `Biopeak-Nexus-BE18.zip`.

## What was added

| Method | Public URL path | Purpose |
| --- | --- | --- |
| `POST` | `/webhooks/rook/data/` | Receive and normalize signed ROOK Data Webhook summaries and events. |

This path is for **server-to-server delivery from ROOK**, not an API called
by the Biopeak mobile app. It does not require a Biopeak JWT, but it *does*
require correct `X-ROOK-HASH` HMAC-SHA256 signatures and a matching `client_uuid`.
Do not put `https://webhooks.tryrook.io/` as your Biopeak webhook endpoint; the
ROOK Portal needs an HTTPS URL **hosted on your backend domain**.

No model or migration has been created. Existing tables are reused:
`RookWebhookReceipt` for idempotent receipts/corrections,
`RookMemberIdentity` and `WearableConnection` for user/source association,
`WearableConsent` for permission checks,
`HealthDailySummary` / `HealthDomainSnapshot` for normalized metrics and cards.
No extra DB table. **Notification webhook is disabled:** the public
`POST /webhooks/rook/notification/` route is not registered (404).

## Required .env keys

Use the prefix matching your settings module (`DEV_`, `STG_`, or `PRD_`):

```dotenv
STG_ROOK_BASE_URL=https://api.rook-connect.review
STG_ROOK_CLIENT_UUID=<your-client-uuid>
STG_ROOK_SECRET_KEY=<your-api-secret>
STG_ROOK_WEBHOOK_HASH_KEY=<the-signing-key-shown-by-ROOK-Portal-Signature-tab>
STG_ROOK_CALLBACK_URL=
```

`ROOK_WEBHOOK_HASH_KEY` is **required** for the incoming data webhook. ROOK's
webhook signature documentation describes HMAC with its client signing secret;
use the exact key configured in your ROOK Portal for this client/environment.
If the signing key equals the ROOK API secret for your account, its value may
match `ROOK_SECRET_KEY`, but configure it explicitly. Do not guess or paste
secrets into Bruno/docs. The old `ROOK_ALLOW_UNSIGNED_WEBHOOKS` option no
longer bypasses webhook validation. For production, switch to `PRD_` values
and the production API base URL `https://api.rook-connect.com`.

Any pre-existing queue URLs for the separate historical/manual ROOK API fetch
workers stay as they were; webhook reception does not add a new queue or table.

## Setup in the ROOK Portal

1. Deploy the updated backend at a publicly reachable **HTTPS** domain.
2. In the ROOK Portal, choose your Client and correct Sandbox/Production
   environment. Open **Setup > Webhook > Signature**. Copy the signing key into
   the appropriate `*_ROOK_WEBHOOK_HASH_KEY` backend secret environment variable.
3. Set **Data Webhook** URL to
   `https://YOUR-BACKEND-DOMAIN/webhooks/rook/data/` (trailing slash included).
   Click **Test webhook**. ROOK expects HTTP `200`, `201`, or `202`.
4. **Disable/remove the Notification Webhook destination** in the ROOK Portal.
   Do not configure `/webhooks/rook/notification/` because this API no longer exists.
5. Keep your normal mobile Connect -> `/rook/return` ->
   `/api/v1/devices/providers/?refresh=true` flow unchanged.
6. Connect a supported provider to a registered ROOK user with **active
   wearable consent**. Then wait for ROOK to extract and deliver real health
   records. Test webhooks prove delivery reachability, not necessarily that a
   real health summary was stored for a recognized and consented user.
7. Check the existing `RookWebhookReceipt` row and `HealthDailySummary`/
   `HealthDomainSnapshot` rows; confirm the user's dashboard via
   `GET /api/v1/health/domain-summary/` and detail endpoint.

## Processing and response behavior

```text
Wearable -> ROOK collects/normalizes metrics
         -> POST /webhooks/rook/data/ with X-ROOK-HASH
         -> validate JSON + client UUID + HMAC
         -> identify ROOK user, verify consent + active provider
         -> existing receipt dedup + document version handling
         -> existing normalization/daily contributions + analytics
         -> 200 only after the transaction completes
         -> mobile app reads updated dashboard from Biopeak API
```

Only the Data Webhook is accepted by this backend. Device authorization is
verified through the existing ROOK API worker/provider refresh logic; receiving
health data does not bypass consent or authorization checks. Data webhooks
are rejected for revoked consent or inactive/unlinked sources by the existing
ingestion rules.

| HTTP status | Meaning / action |
| --- | --- |
| `200` | Signed delivery accepted, skipped under current consent/source policy, or idempotent duplicate. |
| `400`, `415`, `422` | Malformed/unsupported body. Fix provider/test payload. |
| `403` | Wrong client UUID or invalid/absent signature. Check signing key. |
| `413` | Document exceeds size limit. |
| `503` | Verification is not configured, ingestion/DB failed, or concurrency retry needed. ROOK will retry. |

This implementation handles the data webhook synchronously; long processing
could exceed an upstream timeout. ROOK documents retries at 2h/24h/48h after
failure. Validate production timeout/latency under real payload sizes and
consider **moving receipt normalization onto a worker** later if necessary;
no extra table is required to do that because receipts already have a QUEUED
state. Configure webserver/proxy body limit to at least 16 MB (ROOK maximum).
The Django request memory limit is set to 16 MB in `core/settings/base.py`.

**Live** means data is pushed to our backend when ROOK extracts it; it does not
mean a continuous per-second smartwatch stream. Some summaries are produced
at daily extraction times. A new webhook **does not push an update to the mobile
screen automatically**; the mobile app must re-request the dashboard (or a
separately implemented real-time transport must notify it).

## Test commands

```bash
python manage.py check
python manage.py check_rook_configuration --strict
python manage.py test wearables.tests.test_signature wearables.tests.test_rook_webhooks wearables.tests.test_ingestion wearables.tests.test_notifications
```

The current artifact is prepared offline; it must be deployed, configured in
ROOK Portal, and exercised against a real sandbox user to verify actual delivery.
No external ROOK account or deployed backend was accessed during preparation.

Sources:
- https://docs.tryrook.io/docs/rookconnect/data_delivery/
- https://support.tryrook.io/en/articles/16875516-how-do-i-set-up-webhooks-in-the-rook-portal
