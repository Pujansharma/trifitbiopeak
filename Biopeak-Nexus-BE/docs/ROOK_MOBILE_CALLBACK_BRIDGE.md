# ROOK OAuth return bridge for React Native

## Scope

This change **only adds a public browser return bridge**. It does not alter
ROOK connection creation, signed webhooks, patient records, authentication,
existing provider state checks, or the existing `/r/<state-token>/...` secure
OAuth callback. No migration or new third-party dependency is required.

## Frontend request

The React Native app calls `POST /devices/connect/` with the existing Biopeak
JWT and customer profile context. Send the following in the JSON body:

```json
{
  "data_source": "Garmin",
  "consent_accepted": true,
  "consent_version": "v1",
  "historical_days": 7,
  "redirect_url": "https://trifitbiopeak.onrender.com/rook/return"
}
```

The full HTTPS callback URL is **46 characters**, under the 50-character
limit in the supplied ROOK authorizer documentation. The server returns
`data.authorizationUrl`; the app opens that URL in the provider auth flow.

After authorization ROOK may navigate to:

```
https://trifitbiopeak.onrender.com/rook/return/client_uuid/<client_uuid>/user_id/<user_id>
```

The public view sends HTTP 302 with a `Location` of
`biopeak://oauth-callback` and, when present, limited URL-encoded navigation
parameters. Android/iOS must register the `biopeak` scheme and handle the
`oauth-callback` destination.

### Critical safety requirement

The callback **is not proof of authorization**. Values such as `status`,
`error`, `user_id` and `client_uuid` are navigation context received from an
unauthenticated browser request. The app MUST call
`GET /devices/?refresh=true` using its authenticated Biopeak session and
`X-Customer-Profile-ID` before displaying the provider as authorized. Never
use query parameters to grant tokens, modify profiles, or mark connections
as connected. Do not log or display authorization URLs containing secrets.

## Render settings for this explicit bridge

The existing code in `wearables/services/connections.py` prefers a separately
configured, server-managed `/r/<state-token>` callback when
`ROOK_CALLBACK_URL` is set. That secure path is **intentionally unchanged**.
To use **this new `/rook/return` flow** instead:

* Leave `PRD_ROOK_CALLBACK_URL` unset (or empty) on Render. Otherwise the
  backend overrides the `redirect_url` supplied by the frontend.
* Set `PRD_ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS=trifitbiopeak.onrender.com` so
  `DeviceConnectSerializer.validate_redirect_url()` accepts that HTTPS host.
* Keep your normal ROOK credentials and `WEARABLES_ENABLED` values configured.

If your ROOK account requires an allowlisted redirect URL, register the exact
HTTPS base callback there; confirm this with the actual ROOK account settings.

The earlier `/r/<state-token>` callback and its one-time server state were not
replaced because the user requested no existing-code rewrites. The two flows
are alternatives; choose explicitly in your Render environment. On Render,
`https://trifitbiopeak.onrender.com/r/<16-character-state>` is **53
characters**, exceeding the documented ROOK 50-character parameter limit.
A shorter dedicated domain is needed if using the existing stateful callback
unchanged.

## Tests

```powershell
$env:DJANGO_SETTINGS_MODULE = "core.settings.development"
uv run python manage.py check
uv run python manage.py test wearables.tests.test_oauth_callback_bridge
```

After deploying to Render:

```powershell
curl.exe -i "https://trifitbiopeak.onrender.com/rook/return"
```

Expected HTTP 302 with `Location: biopeak://oauth-callback`.
A browser or `curl` success **does not** validate an installed app's deep-link
handling or ROOK provider authorization. Test both platforms with a real
provider, including cancellation and pending authorization.
