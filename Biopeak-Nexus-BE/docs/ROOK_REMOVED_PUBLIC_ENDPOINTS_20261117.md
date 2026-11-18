# ROOK public endpoint cleanup (17 November 2026)

Base: `Biopeak-Nexus-BE_HealthTimeline_Removed_Endpoints_Updated (1).zip`.

> Historical note: This describes the 17 November removal. As of 18 November,
> the **data** webhook has been restored, while the **notification** webhook
> remains removed. Refer to `docs/ROOK_WEBHOOK_RESTORED.md` for current behavior.

## Current routes

- `GET /api/v1/devices/providers/` **retained**, and `GET /api/v1/devices/providers/?refresh=true` **retained**.
- `POST /api/v1/devices/connect/`, `POST /api/v1/devices/disconnect/`, `POST /api/v1/devices/sync/`, `PATCH /api/v1/devices/native-status/` **retained**.
- `GET /rook/return/` (mobile OAuth return) **retained**.
- `GET /api/v1/health/domain-summary/` and `GET /api/v1/health/domain-summary/<domain>/` **retained**.
- `POST /api/v1/devices/consent/revoke/` **removed**.
- `GET /api/v1/devices/sdk-config/` **removed**.
- `POST /webhooks/rook/data/` and `POST /webhooks/rook/notification/` **removed**.
- Old `/r/<state>/...` OAuth endpoint and `/api/v1/health/timeline/` remain **removed** from this uploaded baseline.

## Exact file changes

- `wearables/device_urls.py`: delete consent-revoke and sdk-config imports and routes, keep provider/sync/native/connect/disconnect entries.
- `wearables/views.py`: remove `DeviceSDKConfigView` and its secret-distribution endpoint; restore missing `DeviceRetrySyncView` from previously working baseline (necessary to make device URL imports valid). Do not change Connect/Disconnect/Provider/Native implementations.
- `webhooks/urls.py`: remove **only** `path("rook/", include("webhooks.rook.urls"))`. Non-ROOK webhooks remain available.
- `webhooks/rook/urls.py`, `webhooks/rook/views.py`, `webhooks/rook/__init__.py`: delete retired HTTP webhook module. The **service** `wearables/services/ingestion.py` is retained for API fetch workers. The receipt/dedup model and internal notification service are retained.
- `wearables/management/commands/check_rook_configuration.py`: signing-key setting no longer required for a retired HTTP endpoint. Other ROOK API readiness checks remain.
- `wearables/tests/test_device_api_contract_refactor.py`: enforce retained provider routes and 404 for retired routes.
- `wearables/tests/test_rook_deployment_configuration.py` and `test_older_pr143_security_cache_remap.py`: update the now-obsolete SDK/webhook test expectations.
- `bruno/webhooks/rook/`: remove obsolete public HTTP webhook requests; keep all other Bruno collections.
- `.env.example`: remove obsolete public webhook instructions. Never check real `.env` into source control.

## Important operational conditions

1. **Disable both webhook subscriptions in the ROOK dashboard**, or ROOK will keep posting to 404 endpoints. This package cannot change the external dashboard.
2. No model or migration changes are needed for HTTP route retirement. Keep `RookWebhookReceipt` and `HealthDailySummary` because ROOK API-pull ingestion uses them.
3. The **public** consent-revoke operation was removed. Internal `revoke_wearable_consent` remains for other/internal use, but no longer has a public endpoint; validate customer consent-withdrawal behavior through your approved account/privacy workflow.
4. `PATCH /api/v1/devices/native-status/` updates **existing native connection** records only, despite the mobile SDK configuration endpoint removal.
5. The original ROOK connect flow may still return HTTP 503 if provisioning/credentials/allowed hosts or provider authorizer are unavailable. API route cleanup does not fix those runtime conditions.
6. ROOK notification push will not update statuses after removal; provider refresh and queued auth jobs are the supported mechanisms. API-based fetch workers (`process_rook_data_fetch_jobs`, `process_rook_auth_jobs`) remain unchanged.
7. `.env`, `.git`, cached data and live test bearer tokens are excluded from this distributed ZIP. Preserve local secrets separately.

## Local verification (Python 3.14 and installed application dependencies)

```powershell
uv run python manage.py check
uv run python manage.py check_rook_configuration --strict
uv run python manage.py test wearables.tests.test_device_api_contract_refactor wearables.tests.test_rook_deployment_configuration wearables.tests.test_older_pr143_security_cache_remap -v 2
```

Also test real connect/refresh/sync/worker operation with an authorized, non-production ROOK account and staged database before push. Source-level and syntax checks alone do not verify live provider behavior.
