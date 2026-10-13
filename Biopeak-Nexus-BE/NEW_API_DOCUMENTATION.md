# Biopeak Nexus Backend — Newly Added API Documentation

**Audience:** Product, QA, mobile developers, and non-technical reviewers  
**Deployment base URL:** `https://trifitbiopeak.onrender.com/`

This document covers only APIs/features identified in the Phase 1 ROOK snapshot that were added to the older backend. It is not the complete API catalogue.

> **Important:** The base URL was checked and returned `{"detail":"OK"}`. Individual endpoints below have not been live-tested here. Their availability depends on deployment, database migrations, environment variables, ROOK configuration, and feature flags.

## Before using the APIs

- **Customer APIs:** Send the Biopeak customer JWT in `Authorization: Bearer <token>`.
- **Profile selection:** Wearable APIs can use `X-Customer-Profile-ID: <customer-profile-uuid>` to select a profile owned by the signed-in customer. If omitted, the main profile is used.
- **JSON requests:** Use `Content-Type: application/json` for POST requests with JSON bodies.
- **Responses:** Normal Biopeak API responses use a `detail` message and a `data` object. Webhook endpoints return HTTP `202` when accepted.
- **Feature flags:** Wearable APIs can return `404` when wearables are disabled. They can also require the profile's Wearables feature to be enabled.

---

## 1. Wearable device connections

These APIs let the mobile app connect supported wearable providers, check connection status, and disconnect a provider without deleting previously collected health history.

### 1.1 List connected devices

`GET /devices/`

Full URL: `https://trifitbiopeak.onrender.com/devices/`

**Purpose:** Returns the customer's wearable connections and their current status.

Optional query parameter:

| Parameter | Values | Meaning |
|---|---|---|
| `refresh` | `true` or `1` | Ask the backend to refresh providers that are still authorizing. |

Example: `GET /devices/?refresh=true`

### 1.2 Start connecting a wearable

`POST /devices/connect/`

**Purpose:** Records the user's consent and starts the provider authorization or native SDK setup.

Example request:

```json
{
  "data_source": "Garmin",
  "consent_accepted": true,
  "consent_version": "v1",
  "historical_days": 29,
  "timezone_name": "Asia/Kolkata",
  "preferred_units": "metric"
}
```

Required fields: `data_source`, `consent_accepted`. Consent must be `true`.

Optional fields: `consent_version`, `historical_days` (0–180), `redirect_url`, `timezone_name`, `preferred_units`.

Supported API providers include Garmin, Fitbit, Oura, Polar, Withings, Whoop, and Dexcom. Native app sources include Apple Health, Health Connect, and Samsung Health; actual support depends on ROOK and mobile SDK configuration.

**Success:** HTTP `201`, with connection information and, where applicable, an `authorizationUrl` for the user to continue connecting.

### 1.3 Disconnect a wearable

`POST /devices/disconnect/`

Example request:

```json
{
  "data_source": "Garmin"
}
```

**Purpose:** Disconnects the selected provider. Historical health data is retained.

### 1.4 Get mobile SDK configuration

`GET /devices/sdk-config/`

**Purpose:** Returns ROOK SDK configuration after a native wearable connection has been initiated. It returns an error if native setup has not started or the required SDK configuration is missing.

### 1.5 Update native wearable status

`POST /devices/native-status/`

Example request:

```json
{
  "data_source": "Health Connect",
  "sdk_linked": true,
  "permission_status": "granted",
  "capabilities": ["sleep", "activity", "heart"],
  "timezone_name": "Asia/Kolkata",
  "historical_days": 30
}
```

`data_source`, `sdk_linked`, and `permission_status` are required. `capabilities`, `timezone_name`, and `historical_days` are optional. Use the permission values accepted by the API schema in the deployed version.

---

## 2. Health dashboard and history

These APIs provide health data collected through the wearable integration. The app should display the values and trends returned by the backend rather than calculate its own trends.

### 2.1 Get all health dashboard cards

`GET /health/dashboard/`

Full URL: `https://trifitbiopeak.onrender.com/health/dashboard/`

**Purpose:** Returns the dashboard data for the supported health areas.

### 2.2 Get one health area

`GET /health/{domain}/?days=90`

Supported domains:

- `sleep`
- `activity`
- `heart`
- `recovery`
- `body`
- `workouts`

`days` is optional and can be from `1` to `365` (default `90`).

Example: `GET /health/sleep/?days=30`

**Purpose:** Returns the selected health area, including available values, graphs/trends, state, and relevant actions/messages.

### 2.3 Get health timeline observations

`GET /health/timeline/`

Optional query parameters:

| Parameter | Meaning |
|---|---|
| `start` | Start date (`YYYY-MM-DD`) |
| `end` | End date (`YYYY-MM-DD`), must not be before `start` |
| `domain` | One of the supported health domains listed above |
| `offset` | Number of records to skip; default `0` |
| `limit` | Page size from `1` to `200`; default `50` |

Example: `GET /health/timeline/?start=2026-09-01&end=2026-09-30&domain=sleep&limit=50`

---

## 3. ROOK webhook endpoints

These endpoints are called by ROOK, not by the mobile app. They receive health data and connection/import notifications.

### 3.1 Receive health data

`POST /webhooks/rook/data/`

**Purpose:** Accepts ROOK health documents for processing. A successful acceptance returns HTTP `202`.

The request must follow the configured ROOK webhook format. When webhook signing is configured, include the `X-ROOK-HASH` signature header. Invalid signatures are rejected. Signed v2 deliveries must contain one document per request.

### 3.2 Receive connection/import notifications

`POST /webhooks/rook/notification/`

**Purpose:** Receives ROOK notifications such as connection, disconnection, or import status changes. Requires a JSON object and the valid signature when signing is enabled. Accepted notifications return HTTP `202`.

**Configuration needed:** ROOK credentials, webhook hash key, ROOK portal webhook setup, and the wearable feature flags must be configured in the deployment environment before these endpoints can work in production.

---

## 4. Customer appointments list

### Get appointments for a customer profile

`GET /appointments/customer-appointments/{customer_profile_id}/`

Full URL pattern: `https://trifitbiopeak.onrender.com/appointments/customer-appointments/{customer_profile_id}/`

**Purpose:** Returns appointments belonging to the authenticated customer's own active profile. The profile UUID must belong to the logged-in customer.

Optional query parameter:

| Parameter | Values | Meaning |
|---|---|---|
| `therapy_service_program` | `1` or `0` | Filter appointments to those with or without a therapy service program. |

Example: `GET /appointments/customer-appointments/00000000-0000-0000-0000-000000000000/`

Replace the example UUID with a real customer profile UUID. This endpoint requires a customer JWT.

---

## 5. App download redirect and click tracking

### Open the app download link

`GET /app/`

Full URL: `https://trifitbiopeak.onrender.com/app/`

**Purpose:** Detects the user's device platform and redirects to the configured app destination. If a platform cannot be resolved or no destination is configured, it displays a page with available app links.

Optional query parameters:

| Parameter | Example | Meaning |
|---|---|---|
| `platform` | `ios` or `android` | Optional platform override. |
| `src` | `campaign_banner` | Source label used for click tracking. |
| `campaign` | `october_launch` | Campaign label used for click tracking. |

Example: `https://trifitbiopeak.onrender.com/app/?src=campaign_banner&campaign=october_launch`

This endpoint does not require customer login. Click tracking is recorded for normal user visits; recognized bots are excluded.

---

## 6. Related background jobs (not HTTP APIs)

These commands were added for the wearable processing workflow and run from the server/scheduled worker, not through an HTTP request:

- `uv run python manage.py process_health_jobs` — processes queued health data, analytics, connection, and recovery jobs.
- `uv run python manage.py enqueue_health_freshness_checks` — queues checks for stale/missing health data and eligible recovery pulls.
- `uv run python manage.py enqueue_appointment_reminders` — queues appointment reminder work.

Run these only after deployment settings and database migrations have been reviewed.

---

## 7. Common errors and setup notes

- `401 Unauthorized`: customer JWT is missing or invalid.
- `403 Forbidden`: the request does not have permission, or webhook signature validation failed.
- `404 Not Found`: the route/resource does not exist, or wearable functionality is disabled for the environment/profile.
- `400 Bad Request`: request fields or query parameters are invalid.
- `503 Service Unavailable`: required ROOK or SDK configuration is missing, or the provider service is unavailable.

**Deployment reminder:** The endpoint definitions come from the merged source code. Confirm migrations have been applied, feature flags are enabled, app store destination URLs are configured, and ROOK credentials/webhooks are set before treating these routes as production-ready.





temporary code has changed on :-
1:- accounts/management/commands/_init_.py
2:- accounts/management/commands/create_test_mobile_accounts.py
3:- accounts/_init_.py