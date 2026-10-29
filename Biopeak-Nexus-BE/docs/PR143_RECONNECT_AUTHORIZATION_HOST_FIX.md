# PR #143: reconnect blocked by ROOK authorizer hostname validation

## What happened

When a user has already authorized a ROOK API source, `/authorizer` may return
`authorized=true` and no URL. After revocation, a subsequent authorization
requires a new HTTPS URL. The backend correctly refuses URLs when
`ROOK_AUTHORIZATION_ALLOWED_HOSTS` is empty or excludes the returned hostname.
This can make reconnect fail with HTTP 502 while the first connection appeared
successful. **Do not bypass the allowlist.**

## Required configuration (not shipped as a secret or auto-approval)

Set this in the relevant environment's `.env` or secrets manager **before**
initiating API-provider Connect / Reconnect:

```dotenv
DEV_ROOK_AUTHORIZATION_ALLOWED_HOSTS=connect.garmin.com
```

Use `STG_ROOK_AUTHORIZATION_ALLOWED_HOSTS` in staging and
`PRD_ROOK_AUTHORIZATION_ALLOWED_HOSTS` in production. For other providers,
add only exact, independently verified authorizer hostnames after checking the
ROOK developer portal/provider documentation. Do not add schemes, paths,
wildcards, arbitrary HTTPS domains or provider hosts from untrusted requests.
`ROOK_PROVISIONED_SOURCES` is a separate allowlist of approved *providers*.

Check what Django actually loaded (no secrets printed):

```bash
uv run python manage.py shell -c "from django.conf import settings; print(settings.ROOK_AUTHORIZATION_ALLOWED_HOSTS)"
uv run python manage.py check_rook_configuration --strict
```

The backend now returns a clear **503** if the allowlist is not configured,
without modifying the disconnected state. If ROOK supplies an unexpected host,
validation still returns **502** and logs *only the rejected hostname and
provider name*, not the authorization URL or its potentially sensitive query.
Confirm the host with ROOK independently before adding it to the allowlist.

## Reconnect safeguards

- A failed reconnect authorizer stays **disconnected** and retains the revoked
  authorization state; the user can retry after correcting configuration.
- A retry of a previously failed reconnect from the older build retains the
  disconnected origin, enabling proper **historical re-import** after ROOK
  confirms new authorization.
- Valid authorizer URLs remain HTTPS-only, exact-host matched, without URL
  credentials or custom ports. Garmin keeps the additional pinned hostname.
- A redirect back to the app is not itself proof of authorization: the backend
  rechecks with ROOK before transitioning to an authorized state.

## Acceptance steps

1. Confirm provider approval and trusted-host configuration in the active
   Django environment; restart the process after settings changes.
2. Connect and authorize Garmin in ROOK's sandbox.
3. Disconnect and verify ROOK revocation, then request Connect again.
4. Open the returned `authorizationUrl` in the supported system browser.
5. Authorize in ROOK; verify `GET /devices/?refresh=true` transitions into
   historical re-import, and jobs process the data.
6. Test an empty allowlist, unknown HTTPS host, wrong Garmin host and repeat
   taps. Unknown hosts must remain blocked.

Run regression tests with Python 3.14 and PostgreSQL:

```bash
uv run python manage.py test wearables.tests.test_reconnect_authorization_host
uv run python manage.py test wearables.tests.test_repeated_device_connect
uv run python manage.py test wearables.tests.test_pr143_followup_fixes
```

ROOK live sandbox, callback and database integration cannot be certified using
source-level checks alone.
