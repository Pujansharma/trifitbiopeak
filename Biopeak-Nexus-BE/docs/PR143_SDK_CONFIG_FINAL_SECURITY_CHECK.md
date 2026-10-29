# PR #143 — Native SDK Configuration: reviewer security and frontend handover

## Code-level review result

`GET /api/v1/devices/sdk-config/` already emits the standard `{detail, data}` envelope with
`clientUuid`, `secret`, `environment`, and `rookUserId`. The `secret` is the **ROOK SDK Authentication
Secret Word**, NOT the server ROOK API Secret Key used for Basic authentication.

Official ROOK reference:
- https://support.tryrook.io/en/articles/16875509-how-do-rook-sandbox-and-production-credentials-work
- https://docs.tryrook.io/docs/rookconnect/sdk/reactnative/rook-sdk/api-reference/
- https://docs.tryrook.io/docs/rookconnect/sdk/reactnative/fundamentals/updateuserid/

The backend denies credential responses unless all these conditions hold:
1. JWT identifies a customer and authorizes the requested customer profile.
2. Wearables and the profile's wearable feature are enabled.
3. The profile has a current native connection that is neither disconnected, authorization-expired,
   permission-denied, nor never-connected, and whose native source remains provisioned.
4. The profile has active wearable-ingestion consent.
5. `ROOK_SDK_CLIENT_UUID` and `ROOK_SDK_SECRET` are present.
6. `ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=true` is explicitly enabled after SDK Secret Word approval.
7. `ROOK_SDK_SECRET != ROOK_SECRET_KEY`, even in development.
8. Successful responses use `Cache-Control: no-store, private`.

ROOK mobile credentials are distributed to a handset, so they must be considered extractable.
No JWT endpoint can turn a mobile-held SDK Secret Word into a server-only secret. The registered
Android package name/iOS bundle ID and separate revocation/rotation are essential.

## Correct frontend order (per user and profile)

1. After authenticated login and profile selection, call
   `POST /api/v1/devices/connect/` with e.g.
   `{ "data_source": "Apple Health", "consent_accepted": true, "consent_version": "v1" }`.
   Native source must appear as selectable in `GET /api/v1/devices/providers/`.
2. Call `GET /api/v1/devices/sdk-config/` with the same JWT/profile.
3. Initialize the ROOK mobile SDK with `data.clientUuid`, `data.secret`, and `data.environment`.
   The SDK package name/bundle ID must match ROOK Portal SDK Authentication.
4. Call the SDK's `updateUserID(data.rookUserId)` before any sync; changing user IDs resets
   ROOK sync status. Request native health permissions, then sync.
5. Post the outcome to `POST /api/v1/devices/native-status/` and confirm that signed ROOK
   webhooks are normalized to the selected customer profile.

Do not call `sdk-config/` before `connect/`: the existing endpoint deliberately rejects
profiles without a native connection. Returning 400 in that case is expected.

## Environment configuration

Use the appropriate DEV_, STG_, or PRD_ prefix. Values shown are placeholders, not real secrets.

```dotenv
DEV_ROOK_CLIENT_UUID=<UUID for the ROOK sandbox Client>
DEV_ROOK_SECRET_KEY=<ROOK server-side API Secret Key; never return to phone>
DEV_ROOK_SDK_CLIENT_UUID=<same ROOK sandbox Client UUID>
DEV_ROOK_SDK_SECRET=<independent SDK Authentication Secret Word registered to app>
DEV_ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=true
DEV_ROOK_PROVISIONED_SOURCES=Apple Health,Health Connect,Samsung Health
```

Rotate the SDK Secret Word independently from the server API Secret Key.
For production, use the production ROOK Client and production SDK Authentication registration.

`check_rook_configuration --strict` now catches an SDK Client UUID that differs from the
ROOK server Client UUID. It cannot verify that the SDK Secret Word has actually been registered
for the Android/iOS application, nor certify live ROOK security.

## Reviewer acceptance and regression tests

- Verified code response envelope, no-store cache and SDK/server-secret separation.
- Added test coverage for exact JSON keys, disabling distribution, secret equality rejection,
  consent, native connection eligibility, source provisioning and UUID mismatch.
- Run: `uv run python manage.py test wearables.tests.test_pr143_sdk_config_contract`
- Run: `uv run python manage.py test wearables.tests --verbosity 2`
- Run: `uv run python manage.py check_rook_configuration --strict`
- End-to-end proof still needed: actual React Native SDK initialization on iOS/Android
  with registered bundle/package ID, user ID assignment, permission grant, signed webhook,
  disconnect/reconnect, worker drain, and Redis-backed throttling across ECS tasks.

No live credentials, user-identifiable data, models or migrations belong in this patch.
