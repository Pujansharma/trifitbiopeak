# PR #143: verification of three earlier comments

This review is based on `Biopeak-Nexus-BE-PR143-Four-P1-Fixes-Full.zip` and does not replace a real Django/PostgreSQL/ROOK production acceptance test.

## 1. SDK credential distribution (P1)

Status: **Code guard implemented; ROOK Portal approval and mobile testing remain mandatory.**

- `wearables/views.py` denies `GET /devices/sdk-config/` unless there is a native connection, valid wearable consent, both mobile credentials, and the explicit per-environment `ROOK_SDK_CLIENT_CREDENTIALS_PUBLIC=true` flag. The flag defaults to **false**. It also blocks reuse of the server-side `ROOK_SECRET_KEY`, and returns `Cache-Control: no-store, private` for a successful response.
- This follow-up excludes disconnected, expired, and never-connected SDK rows as the only prerequisite to requesting SDK configuration. Reconnect via `POST /devices/connect/` to request a new native authorization.
- Official ROOK SDK documentation describes a client UUID and an app-bound secret for SDK initialization. Before enabling the flag, **register the iOS bundle identifier / Android application ID and its corresponding separate mobile SDK secret in the ROOK Portal** for each environment; confirm with ROOK that this credential is safe to ship to clients and can be rotated separately. Neither this ZIP nor a feature flag proves the upstream credential is provisioned.
- Never copy `ROOK_SECRET_KEY` into `ROOK_SDK_SECRET`. Treat the mobile client secret as potentially discoverable on a compromised handset. Do not log it, return it in other APIs, or cache the config response.
- Rotate the app-bound SDK secret independently from the server API Basic-auth secret; reconfigure affected mobile applications as required by ROOK.

ROOK references:
- https://docs.tryrook.io/docs/rookconnect/sdk/flutter/health-connect/fundamentals/usage-sdk/
- https://docs.tryrook.io/docs/rookconnect/sdk/iOS/

## 2. Per-worker health cache and throttling (P1)

Status: **Health dashboard issue addressed in code; production-wide API throttling requires infrastructure.**

- `CACHES['health']` uses Django `DummyCache` in `core/settings/base.py`, so there is no cross-request process-local health cache.
- `wearables/services/analytics.py` uses `HealthDomainSnapshot` database rows as shared read-through snapshots, invalidated when data changes. Tests cover that the local/dummy cache is not considered shared.
- `CACHES['default']` remains legacy `LocMemCache` for unrelated existing features. DRF's `ScopedRateThrottle` uses the default cache, so limits are **per worker** rather than a global guarantee. This is **not production-complete on multi-worker ECS until a shared throttle backend or WAF/API Gateway rules are confirmed**. The config check now emits a `WEARABLE_EDGE_RATE_LIMIT` warning when using a local default cache.
- Do not claim one global request limit until infrastructure engineering has confirmed the deployed WAF/API Gateway/shared cache behavior and tested it using several ECS tasks.

## 3. Local-date timezone remapping (P2)

Status: **Implemented in code; test on representative data before final review.**

- `wearables/services/ingestion.py::remap_member_local_days` no longer has a function-wide `@transaction.atomic` or an identity row lock. It processes up to 500 `HealthObservation` rows per update transaction, checks the timezone between batches, and rebuilds daily summaries within separate per-day transactions.
- The calculation changes `local_date` from `observed_at` plus the member's IANA timezone. **`observed_at` UTC instants are not changed**.
- The extended regression test checks 510 observations are updated in batches of 500 and 10 and validates the persisted UTC instants.
- Full PostgreSQL verification should include large histories, DST transitions, concurrent timezone changes, worker restart/retry, correction ingestion, and dashboard invalidation. Partial progress after a worker interruption is possible because the design intentionally avoids a single all-or-nothing history-wide transaction; the remap/retry workflow must converge.

## Checks and delivery gate

```powershell
uv run python manage.py check
uv run python manage.py check_rook_configuration --strict
uv run python manage.py test wearables.tests.test_older_pr143_security_cache_remap
uv run python manage.py test wearables.tests.test_pr_review_12_fixes
uv run python manage.py test wearables.tests
```

The last three tests require the intended Python 3.14 Django environment and an appropriate PostgreSQL test DB; ROOK SDK credentials and ingress throttling require upstream/deployment validation. Do not mark either P1 finding fully production-ready solely from static tests.
