# ROOK seven-operation handover — 17 November 2026

## Changes made in this package

This is a targeted backend update of the user's `Biopeak-Nexus-BErefactor.zip`. No model or migration was changed.

| Method | Path | Implemented in | Contract |
| --- | --- | --- | --- |
| POST | `/api/v1/devices/connect/` | `wearables/device_urls.py`, `wearables/views.py`, `services/connections.py` | Existing, unchanged. Returns authorization URL when needed. |
| POST | `/api/v1/devices/disconnect/` | same | Existing, unchanged. |
| GET | `/rook/return/` | `core/urls.py`, `wearables/oauth_callback.py` | Existing 302 browser-to-app redirect, unchanged. |
| GET | `/api/v1/devices/providers/` | `wearables/views.py` | Complete catalogue plus saved API connection status and `nativeStatuses`. |
| GET | `/api/v1/devices/providers/?refresh=true` | same | Refresh pending API authorization first, preserve same JSON shape and return `refreshError` when a handled ROOK failure occurs. |
| POST | `/api/v1/devices/sync/` | `wearables/device_urls.py`, `wearables/views.py` | Existing queued/cooldown sync implementation under the renamed URL. |
| PATCH | `/api/v1/devices/native-status/` | `wearables/views.py` | Existing native connection and active consent required. Complete status fields are currently required in PATCH body. POST returns 405. |

`GET /api/v1/health/timeline/` is not registered in this latest uploaded backend.

### Removed in this package

- GET `/r/<state_token>/client_uuid/<client_uuid>/user_id/<rook_user_id>` and trailing-slash variant. `core/api/urls.py` no longer mounts `wearables.callback_urls`; the public DRF `RookOAuthCallbackView` and its URL module are removed.
- Obsolete Bruno requests for `GET /api/v1/devices/`, `POST /api/v1/devices/retry-sync/`, POST native status, legacy `/r/<state>` and discontinued SDK/consent UI requests. The consent-revoke and SDK-config backend endpoints are removed by the subsequent public-endpoint cleanup.
- Superseded commented-out copies of device provider/native view code in `wearables/views.py`.

### OAuth configuration warning: must be corrected for a successful Connect flow

`connect` still uses the existing `callback_url_for_connection` service and prefers a nonempty `ROOK_CALLBACK_URL`. **That old callback URL now produces 404** because the GET state route is retired. You MUST leave the corresponding `DEV_`, `STG_`, or `PRD_ROOK_CALLBACK_URL` empty/unset and send an approved public HTTPS `redirect_url` ending `/rook/return` in the Connect request. `check_rook_configuration` reports a nonempty legacy callback as **ERROR**.

Set `*_ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS` to the exact HTTPS callback hostname. No provider is authorized by a callback redirect alone; the app must call `GET /api/v1/devices/providers/?refresh=true` with its authenticated customer profile. The existing service logic for the retired server-managed state callback remains internal for now; no database migration is necessary.

### Manual change locations

| File | Change |
| --- | --- |
| `core/api/urls.py` | Remove `path("r/", include("wearables.callback_urls"))`. |
| `wearables/callback_urls.py` | Delete legacy state-token callback route module. |
| `wearables/views.py` | Remove obsolete `RookOAuthCallbackView` class/imports; clean old commented view blocks. Keep active connect/disconnect/provider/sync/PATCH views unchanged. |
| `wearables/management/commands/check_rook_configuration.py` | Flag nonempty legacy callback setting as ERROR. |
| `wearables/tests/test_oauth_callback_bridge.py` | Assert the legacy state URL is not resolvable, retain mobile callback tests. |
| `wearables/tests/test_device_api_contract_refactor.py` | Add full endpoint URL/verb/merged payload offline regression coverage. |
| `wearables/tests/test_rook_deployment_configuration.py` | Add retired-callback configuration guard test. |
| `bruno/wearables/devices/` | Replace obsolete requests with `GET Providers`, `GET Providers Refresh`, `POST Sync`, `PATCH Native Status`. |
| `bruno/wearables/oauth/` | Replace state callback request with retained `GET Mobile Return`. |
| `docs/` | Refresh mobile return and operational docs plus this handover. |
| `bruno/environments/*.bru` | Clear embedded bearer/refresh tokens before sharing ZIP. Re-enter locally. |

### Django regression commands (Python 3.14 project environment)

```powershell
uv run python manage.py check
uv run python manage.py check_rook_configuration
uv run python manage.py test wearables.tests.test_device_api_contract_refactor wearables.tests.test_oauth_callback_bridge wearables.tests.test_rook_deployment_configuration -v 2
uv run python manage.py test wearables.tests -v 2
```

### Smoke-test steps

1. GET providers should return HTTP 200 and `data.providers`, `data.nativeStatuses`, `data.connections`, `data.refreshError`.
2. GET providers with `?refresh=true` should preserve this envelope and verify pending connections; if ROOK fails, inspect `refreshError`.
3. POST connect with an approved API source, consent, valid JWT/profile and approved HTTPS `redirect_url` should return the existing authorization link. **503 is not resolved by route renaming**: check ROOK budgets/credentials/allowed provider auth hosts and backend error payload.
4. GET `/rook/return/` should return 302 to `biopeak://oauth-callback`. GET the legacy `/r/<state>/...` must return 404.
5. After provider OAuth, GET providers `?refresh=true`; confirm actual authorized connection state. Do not trust 302 as proof.
6. POST sync should accept the same source body as old retry-sync, returning 202 for queued/reused work or 200 for cooldown. Ensure a worker actually processes the job.
7. PATCH native-status with the existing native connection and required fields should return 200; POST native-status must return 405.
8. POST disconnect should return the existing response; GET health timeline should still be routed.

### Verification limitations

The offline route/source checks can be run without a database. Full Django regression, PostgreSQL, real ROOK connect/disconnect/refresh and mobile deep-link E2E must be verified in the target environment before push.
