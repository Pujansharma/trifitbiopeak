# ROOK OAuth return bridge for React Native (current)

## Supported flow

1. Authenticated client calls `POST /api/v1/devices/connect/` with the supported ROOK API source, consent, and a short **HTTPS** `redirect_url` such as `https://trifitbiopeak.onrender.com/rook/return` (replace with your real approved public hostname).
2. Register the same HTTPS redirect URL with ROOK if required by your ROOK account. ROOK returns an `authorizationUrl`; the app opens it.
3. ROOK redirects to `GET /rook/return/` and may append `/client_uuid/{uuid}/user_id/{id}` to the path.
4. The backend returns HTTP **302** to the fixed `biopeak://oauth-callback` application URL. Browser parameters are navigation context **only**.
5. The authenticated mobile app calls `GET /api/v1/devices/providers/?refresh=true` with its customer JWT and `X-Customer-Profile-ID` to verify any pending authorizations. Never infer success from the browser redirect alone.

## Configuration (required before deployment)

- `DEV_ROOK_CALLBACK_URL`, `STG_ROOK_CALLBACK_URL`, and `PRD_ROOK_CALLBACK_URL` must remain **empty/unset**. The stateful `/r/<state>/...` GET route has been removed. If a nonempty legacy callback value remains, Connect can create a return URL that no longer exists. `check_rook_configuration` reports this as **ERROR**.
- Set the appropriate `*_ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS` to the actual HTTPS hostname in the `redirect_url` sent by your mobile frontend. No scheme or path in the hosts list; avoid wildcards.
- The explicit `redirect_url` must meet the existing length limit (at most 50 characters) and the ROOK account's registration requirements.
- Confirm that the mobile app registers the `biopeak://oauth-callback` deep link.
- Never expose ROOK API credentials in the browser, and never treat callback URL/query parameters as authenticated provider status.

## What remains unchanged

- `POST /api/v1/devices/connect/`, `POST /api/v1/devices/disconnect/`, `GET /rook/return/` and its ROOK-appended identifier variants, including their source implementation.
- The server uses the existing ROOK authorization-status refresh in the provider catalogue.

## Verification

```powershell
uv run python manage.py check
uv run python manage.py check_rook_configuration
uv run python manage.py test wearables.tests.test_oauth_callback_bridge wearables.tests.test_device_api_contract_refactor -v 2
```

Test the app flow with a real supported ROOK provider. A standalone 302 is **not** evidence that the external OAuth grant succeeded.
