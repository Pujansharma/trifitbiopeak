# API inventory

**Reviewed:** 1 October 2026  

This inventory includes current frontend HTTP API integrations selected using the agreed original-authorship filter, based on endpoint-level Git history. Git establishes authorship of the frontend integrations; backend implementation ownership is not established by this repository. Later edits by other contributors do not change the recorded original author.

## Summary

| Group | Unique endpoints |
| --- | ---: |
| Internal | 20 |
| External | 11 |
| **Total** | **31** |

**Grouping:** routes beginning with `/external/` (ignoring an omitted leading slash) are External; all other listed routes are Internal. These labels describe route namespaces, not service ownership or network exposure. Chat service routes therefore appear under Internal.

**Counting:** each base URL + HTTP method + endpoint template is counted once. Query variants and duplicate wrappers are consolidated. Endpoint strings below retain their source spelling, including leading slashes and `${parameter}` placeholders.

## Base URLs

| Environment variable | Used by |
| --- | --- |
| `VITE_BASE_URL` | Main application authentication, profiles, reports, and feature configuration |
| `VITE_BIOPEAK_CHAT_BASE_URL` | Chat history, streaming, and feedback |
| `VITE_BIOPEAK_BASE_URL` | External customer care team, programs, services, and notifications |

The Biopeak client uses `/biopeak-api` in development and `VITE_BIOPEAK_BASE_URL` outside development. No environment values, credentials, or customer data are included.

## Internal APIs (20)

### Authentication (5)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/auth/api/auth.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| POST | `https://api.metsights.com/auth/request-otp/` | Request an OTP for a phone number and purpose. | `46` |
| POST | `https://api.metsights.com/auth/login-otp/` | Log in using a phone number and OTP. | `53` |
| POST | `https://api.metsights.com/auth/refresh/` | Refresh access and refresh tokens. | `68` |
| GET | `https://api.metsights.com/users/profile/` | Retrieve the authenticated user profile. | `63` |
| GET | `https://api.metsights.com/profiles/` | List available profiles. | `58` |

### Account (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/account/api/account.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| PATCH | `https://api.metsights.com/profiles/${id}/` | Update a profile using form data or a JSON object. | `7` |

### Care team (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/careTeam/api/careTeam.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/specialists/` | List specialists with supplied filters or pagination. | `61` |

### Reports (4)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/reports/api/reports.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/records/` | Retrieve records filtered by code BIOPEAK_HEALTH. | `25` |
| GET | `https://api.metsights.com/records/${recordId}/attachments/` | Retrieve record attachments, optionally filtered by category_type. | `35`, `45` |
| GET | `https://api.metsights.com/reports/precision-reports/${recordId}/consolidated/` | Retrieve the consolidated precision report. | `53` |
| POST | `https://api.metsights.com/records/${recordId}/export-reports/` | Export reports to the supplied email address. | `59` |

### Analysis (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/analysis/api/analysis.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/reports/biopeak-health-reports/${recordId}/` | Retrieve health report details. | `5` |

### Results and trends (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/results/api/trends.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/reports/biopeak-health-reports/${recordId}/trends/` | Retrieve historical biomarker trends. | `5` |

### Action plan (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/actionPlan/api/actionPlan.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/reports/biopeak-health-reports/${recordId}/files/` | Retrieve health report files with supplied filters. | `10` |

### Guidebook (1)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/guidebook/api/guidebook.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/records/${recordId}/personalised-plan/` | Retrieve the personalised plan file reference. | `6` |

### Ask AI: profile configuration (2)

**Base URL:** `VITE_BASE_URL`  
**Source:** `src/features/askAI/api/askAI.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/profiles/${profileId}/features/biopeak-chat/` | Retrieve the profile's chat session ID and API token. | `52` |
| GET | `https://api.metsights.com/profiles/${profileId}/features/` | Retrieve feature configuration for the profile. | `57` |

### Ask AI: chat service (3)

**Base URL:** `VITE_BIOPEAK_CHAT_BASE_URL`  
**Source:** `src/features/askAI/api/askAI.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://biopeak-ai.metsights.com/chat/history/${sessionId}/` | Retrieve conversation history for a chat session. | `19` |
| POST | `https://biopeak-ai.metsights.com/chat/stream/${sessionId}/` | Send a message and receive the streamed response. | `31` |
| POST | `https://biopeak-ai.metsights.com/chat/feedback/${messageId}/` | Submit positive or negative feedback on a message. | `45` |

The streaming endpoint also has a fetch/SSE implementation in `src/features/askAI/hooks/useChatSSE.ts:29`. It is counted once across the Axios wrapper and SSE hook.

## External APIs (11)

### Care team (1)

**Base URL:** `VITE_BIOPEAK_BASE_URL`  
**Source:** `src/features/careTeam/api/careTeam.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-associates/` | Retrieve customer care team associates using phone. | `69` |

### Programs and services (6)

**Base URL:** `VITE_BIOPEAK_BASE_URL`  
**Source:** `src/features/programs/api/programs.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-programs/` | List customer programs using phone and active, complete, or expired filters. | `101` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-programs/summary/` | Retrieve program and session totals using phone. | `111` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-programs/${programId}/` | Retrieve one customer program using phone. | `124` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-programs/${programId}/services/` | List a program's services using phone and optional page. | `138` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-services/${serviceId}/` | Retrieve one service and its program using phone. | `149` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-therapy-services/${serviceId}/redemption-history/` | Retrieve a service's redemption history using phone. | `162` |

The six program and service integrations were later updated to use the current `customer-therapy-` route names. Superseded routes are not counted.

### Notifications (4)

**Base URL:** `VITE_BIOPEAK_BASE_URL`  
**Source:** `src/features/notifications/api/notifications.api.ts:1`

| Method | Endpoint | Purpose | Source line(s) |
| --- | --- | --- | --- |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-notifications/` | Retrieve customer notifications and counts; list requests support phone and page. | `91`, `100` |
| GET | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-notifications/${id}/` | Retrieve notification details using phone. | `107` |
| POST | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-notifications/register/` | Register a notification token using phone, token, and project_id. | `114` |
| POST | `https://<BIOPEAK_EXTERNAL_API_HOST>/external/customer-notifications/deregister/` | Deregister a notification token using phone and token. | `119` |
