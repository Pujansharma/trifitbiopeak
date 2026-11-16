# Leads Frontend API

## OPTIONS /leads/

Returns DRF field metadata for the leads list/create serializer, plus an
`ops_onboarding_email` block used by
`POST /leads/v2/{lead_id}/ops-onboarding-email/`.

```http
OPTIONS /leads/
Authorization: Bearer <access_token>
```

`ops_onboarding_email` includes mail config plus the same DRF field-info shape
used under `actions.POST` (via `LeadOpsOnboardingEmailSerializer`):

```json
{
  "to": ["<OPS_ONBOARDING_EMAIL_TO constant>"],
  "from": "Care <care@biopeak.health>",
  "cc": "Authenticated user email (JWT)",
  "subject_template": "New Client Onboarding | {client_name} | {package_name}",
  "payment_status": {
    "type": "choice",
    "required": false,
    "label": "Payment status",
    "choices": [
      {"value": "COLLECTED", "display_name": "Collected"},
      {"value": "PENDING", "display_name": "Pending"},
      {"value": "PARTIALLY_COLLECTED", "display_name": "Partially Collected"}
    ]
  },
  "onboarding_status": {
    "type": "choice",
    "required": false,
    "label": "Onboarding status",
    "choices": [
      {"value": "COMPLETED", "display_name": "Completed"},
      {"value": "PENDING", "display_name": "Pending"},
      {"value": "NOT_APPLICABLE", "display_name": "Not Applicable"}
    ]
  },
  "consultation_mode": {
    "type": "choice",
    "required": false,
    "label": "Consultation mode",
    "choices": [
      {"value": "ONLINE", "display_name": "Online"},
      {"value": "IN_PERSON", "display_name": "In Person"},
      {"value": "TO_BE_SCHEDULED", "display_name": "To Be Scheduled"}
    ]
  },
  "action_priority": {
    "type": "choice",
    "required": false,
    "label": "Action priority",
    "choices": [
      {"value": "NORMAL", "display_name": "Normal"},
      {"value": "URGENT", "display_name": "Urgent"},
      {"value": "CRITICAL", "display_name": "Critical"}
    ]
  }
}
```

Other body fields (`package_value`, therapy counts, `additional_contacts`, …)
use the same field-info keys as `actions.POST`. `from` is `DEFAULT_FROM_EMAIL`
(`DEV_DEFAULT_FROM_EMAIL`, `STG_DEFAULT_FROM_EMAIL`, or `PRD_DEFAULT_FROM_EMAIL`).
`to` is the hardcoded `OPS_ONBOARDING_EMAIL_TO` constant. `cc` is the
authenticated user's email.

## GET /leads/

Request:

```http
GET /leads/?search=bhaskar&active=1&is_client=0&center_id=9d9f1e6c-7b70-4c0f-b75d-0d9b44b0c111
```

Response:

```json
{
  "success": true,
  "detail": "All data.",
  "data": [
    {
      "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
      "unique_id": "L-0001",
      "first_name": "Bhaskar",
      "last_name": "Reddy",
      "gender": "Male",
      "phone": "+91-9123456780",
      "email": "reddybhaskar@biopeak.com",
      "description": "Interested in wellness program",
      "is_active": true,
      "is_client": false,
      "is_request_sent": false,
      "is_onboarding_sent": false,
      "converted_on": null,
      "home_center": {
        "id": "9d9f1e6c-7b70-4c0f-b75d-0d9b44b0c111",
        "code": "CT-0001",
        "name": "Greenwood",
        "image": null,
        "address": "Greenwood Main Road",
        "address_line_1": "Greenwood Main Road",
        "address_line_2": null,
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
        "pincode": "560001",
        "staff_count": 12,
        "inactive_staff_count": 1,
        "customer_count": 240,
        "inactive_customer_count": 8,
        "is_active": true,
        "created_at": "2026-07-07T10:00:00+05:30",
        "updated_at": "2026-07-07T10:00:00+05:30"
      },
      "customer_profile": null,
      "created_by": {
        "id": "2e6f5d29-7cc0-4e9e-9e3d-fc1f7a111111",
        "email": "admin@biopeak.com",
        "first_name": "Admin",
        "last_name": "User",
        "image": null,
        "last_login": "2026-07-07T09:30:00+05:30"
      },
      "updated_by": null,
      "created_at": "2026-07-07T10:30:00+05:30",
      "updated_at": "2026-07-07T10:30:00+05:30"
    }
  ]
}
```

## POST /leads/

Request:

```http
POST /leads/
```

```json
{
  "first_name": "Bhaskar",
  "last_name": "Reddy",
  "gender": "M",
  "phone": "+91-9123456780",
  "email": "reddybhaskar@biopeak.com",
  "description": "Interested in wellness program",
  "is_active": true,
  "is_client": false
}
```

Response:

```json
{
  "success": true,
  "detail": "Create success.",
  "data": {
    "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
    "unique_id": "L-0001",
    "first_name": "Bhaskar",
    "last_name": "Reddy",
    "gender": "Male",
    "phone": "+91-9123456780",
    "email": "reddybhaskar@biopeak.com",
    "description": "Interested in wellness program",
    "is_active": true,
    "is_client": false,
    "is_request_sent": false,
    "is_onboarding_sent": false,
    "converted_on": null,
    "home_center": null,
    "customer_profile": null,
    "created_by": {
      "id": "2e6f5d29-7cc0-4e9e-9e3d-fc1f7a111111",
      "email": "admin@biopeak.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-07-07T09:30:00+05:30"
    },
    "updated_by": null,
    "created_at": "2026-07-07T10:30:00+05:30",
    "updated_at": "2026-07-07T10:30:00+05:30"
  }
}
```

## GET /leads/{lead_id}/

Request:

```http
GET /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/
```

Response:

```json
{
  "success": true,
  "detail": "Details.",
  "data": {
    "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
    "unique_id": "L-0001",
    "first_name": "Bhaskar",
    "last_name": "Reddy",
    "gender": "Male",
    "phone": "+91-9123456780",
    "email": "reddybhaskar@biopeak.com",
    "description": "Interested in wellness program",
    "is_active": true,
    "is_client": false,
    "is_request_sent": false,
    "is_onboarding_sent": false,
    "converted_on": null,
    "home_center": null,
    "customer_profile": null,
    "created_by": {
      "id": "2e6f5d29-7cc0-4e9e-9e3d-fc1f7a111111",
      "email": "admin@biopeak.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-07-07T09:30:00+05:30"
    },
    "updated_by": null,
    "created_at": "2026-07-07T10:30:00+05:30",
    "updated_at": "2026-07-07T10:30:00+05:30"
  }
}
```

## PATCH /leads/{lead_id}/

Request:

```http
PATCH /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/
```

```json
{
  "is_client": true,
  "is_active": true
}
```

Response:

```json
{
  "success": true,
  "detail": "Updated successfully.",
  "data": {
    "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
    "unique_id": "L-0001",
    "first_name": "Bhaskar",
    "last_name": "Reddy",
    "gender": "Male",
    "phone": "+91-9123456780",
    "email": "reddybhaskar@biopeak.com",
    "description": "Interested in wellness program",
    "is_active": true,
    "is_client": true,
    "is_request_sent": false,
    "is_onboarding_sent": false,
    "converted_on": null,
    "home_center": null,
    "customer_profile": null,
    "created_by": {
      "id": "2e6f5d29-7cc0-4e9e-9e3d-fc1f7a111111",
      "email": "admin@biopeak.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-07-07T09:30:00+05:30"
    },
    "updated_by": {
      "id": "2e6f5d29-7cc0-4e9e-9e3d-fc1f7a111111",
      "email": "admin@biopeak.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-07-07T09:30:00+05:30"
    },
    "created_at": "2026-07-07T10:30:00+05:30",
    "updated_at": "2026-07-07T10:45:00+05:30"
  }
}
```

## POST /leads/v2/{lead_id}/ops-onboarding-email/

Sends the ops onboarding handoff email (SMTP) on the request thread. Does not flip `is_onboarding_sent`. Does not persist `additional_contacts`.

- **To:** hardcoded `OPS_ONBOARDING_EMAIL_TO` in `leads/utils/constants.py`
- **Cc:** JWT user email (required). Missing email → 400 `"Authenticated user must have an email address to CC."`
- **From:** `DEFAULT_FROM_EMAIL` from env (`DEV_DEFAULT_FROM_EMAIL`, `STG_DEFAULT_FROM_EMAIL`, or `PRD_DEFAULT_FROM_EMAIL`)
- **Subject:** `New Client Onboarding | {Client Name} | {Lead.packages labels}`

Server fills client name/email/phone/DOB, address (street, state, pincode) and city/country from default (or latest) `CustomerProfileAddress` when present, programme from `Lead.packages`, clinic from `home_center`, Lead ID, and Regards from JWT full name. Null/omit body fields render as `—`. `payment_status`, `onboarding_status`, `consultation_mode`, and `action_priority` render as choice labels. SMTP failure → 503 `"Could not send the onboarding email."`

Request:

```http
POST /leads/v2/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/ops-onboarding-email/
Authorization: Bearer <access_token>
Content-Type: application/json
```

```json
{
  "package_value": "₹62,000",
  "payment_status": "COLLECTED",
  "therapy_paid_count": 3,
  "therapy_paid_notes": null,
  "therapy_complimentary_count": 1,
  "therapy_complimentary_notes": null,
  "onboarding_status": "PENDING",
  "consultation_mode": "TO_BE_SCHEDULED",
  "preferred_consultation_date": null,
  "preferred_consultation_time": null,
  "preferred_consultation_notes": null,
  "preferred_home_assessment_notes": null,
  "preferred_clinic_assessment_notes": null,
  "tentative_assessment_date": null,
  "test_kit_delivery": false,
  "special_instruction_notes": null,
  "additional_contacts": [
    {
      "name": "Priya Verma",
      "relationship": "Spouse",
      "email": "priya@example.com",
      "phone": "+919876543210"
    }
  ],
  "action_note": "Schedule IC this week.",
  "action_priority": "NORMAL"
}
```

Enums:

- `payment_status`: `COLLECTED` | `PENDING` | `PARTIALLY_COLLECTED`
- `onboarding_status`: `COMPLETED` | `PENDING` | `NOT_APPLICABLE`
- `consultation_mode`: `ONLINE` | `IN_PERSON` | `TO_BE_SCHEDULED`
- `action_priority`: `NORMAL` | `URGENT` | `CRITICAL`

Response:

```json
{
  "detail": "Onboarding email sent."
}
```

## POST /leads/{lead_id}/share-onboarding/

Request:

```http
POST /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/share-onboarding/
```

```json
{}
```

Response:

```json
{
  "success": true,
  "detail": "Create success.",
  "data": {
    "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
    "is_request_sent": true,
    "is_onboarding_sent": true
  }
}
```

## POST /leads/{lead_id}/convert-client/

Request:

```http
POST /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/convert-client/
```

```json
{}
```

Response:

```json
{
  "success": true,
  "detail": "Create success.",
  "data": {
    "id": "1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10",
    "is_client": true,
    "converted_on": "2026-07-07T11:00:00+05:30",
    "customer_profile": "7a3d1172-21a7-4697-9d31-62c33fdc2222"
  }
}
```

## GET /leads/{lead_id}/available-packages/

Request:

```http
GET /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/available-packages/
```

Response:

```json
{
  "success": true,
  "detail": "All data.",
  "data": []
}
```

## POST /leads/{lead_id}/assign-package/

Request:

```http
POST /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/assign-package/
```

```json
{
  "add": [
    {
      "id": "8c9f4f66-2bc8-4a7c-8577-88c11f333333"
    }
  ],
  "remove": [
    {
      "id": "0936634b-79c2-46c8-8b68-dc702f444444"
    }
  ]
}
```

Response:

```json
{
  "success": false,
  "detail": "Composite package assignment is unavailable until composite models are implemented."
}
```

## GET /leads/{lead_id}/packages/

Request:

```http
GET /leads/1f8f96f2-6d7e-4d52-9d1f-6fd7e09b2c10/packages/
```

Response:

```json
{
  "success": true,
  "detail": "All data.",
  "data": []
}
```
