# Lead Composite Program Template — ePRD

Authenticated endpoints use Bearer tokens.

## Logical Flow

1. **List program templates** — Filter the catalogue and select an active template.
2. **Assign a template to the lead** — Save, replace, or clear the selection before conversion.
3. **Convert and view the program** — Use the usual v2 convert-client action, then refresh the client's profile programs list.

Admins and associates can use these endpoints; customers cannot.

## 1. List program templates

GET (Authenticated): `<baseURL>/programs/composites/templates/`

### Params

| Name | In | Required | Description |
| --- | --- | --- | --- |
| `therapy` | query | No | `1`: therapy count ≥1; `0`: count =0. |
| `assessment` | query | No | `1`: assessment count ≥1; `0`: count =0. |
| `consultation` | query | No | `1`: consultation count ≥1; `0`: count =0. |
| `active` | query | No | `1`: active; `0`: inactive; omitted includes both. |
| `search` | query | No | Case-insensitive code/name substring; surrounding spaces trimmed. |
| `code` | query | No | Case-insensitive code substring; surrounding spaces trimmed. |
| `page` | query | No | Page number; default `1`. |
| `limit` | query | No | Page size; default `10`, maximum `50`. |

Filters combine with AND. Omitted/invalid category or active values impose no restriction. Use `active=1` for assignable selections; `therapy=1&assessment=1&consultation=0` selects templates containing therapy and assessment services without consultation services.

### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01a18ad0-7000-7000-8000-000000000001",
      "code": "WELLNESS",
      "name": "Wellness Package",
      "description": "Baseline assessment and therapy sessions.",
      "assessment_services_count": 1,
      "therapy_services_count": 1,
      "consultation_services_count": 0,
      "services_count": 2,
      "is_active": true,
      "created_at": "2026-11-04T09:00:00+05:30",
      "updated_at": "2026-11-04T09:00:00+05:30",
      "created_by": {
        "id": "01a18ad0-7000-7000-8000-000000000005",
        "email": "admin@example.com",
        "first_name": "Admin",
        "last_name": "User",
        "image": null,
        "last_login": "2026-11-04T09:00:00+05:30"
      }
    }
  ]
}
```

Use the selected `data[].id` as `composite_template_id`. No matches return `count: 0` and `data: []`.

## 2. Assign a template to the lead

PATCH (Authenticated): `<baseURL>/leads/v2/<lead_id>/`

### Params

| Name | In | Required | Description |
| --- | --- | --- | --- |
| `lead_id` | path | Yes | Lead UUID. |

### Payload

For this flow, send only `composite_template_id`. Existing lead-edit fields remain accepted:

| Field | Required | Description |
| --- | --- | --- |
| `composite_template_id` | No | Active template UUID; `null` clears; omission preserves. |
| `first_name` | No | Nonblank text; maximum 100 characters. |
| `last_name` | No | Nonblank text; maximum 100 characters. |
| `gender` | No | `"0"`: Male; `"1"`: Female; `"2"`: Other. |
| `age` | No | Number; derives birth date when date omitted. |
| `date_of_birth` | No | `YYYY-MM-DD`; null allowed. |
| `email` | No | Email; blank/null allowed. |
| `description` | No | Text; blank/null allowed. |
| `is_active` | No | Boolean. |
| `is_client` | No | Boolean; does not perform client conversion. |
| `is_invited` | No | Boolean. |
| `is_onboarding_sent` | No | Boolean; also editable after conversion. |
| `packages` | No | Array of `P001`–`P006`; empty/null allowed. |
| `home_center_id` | No | Existing center UUID. |

The selection is optional and does not create a program yet. After conversion, template writes—including the same UUID or `null`—are rejected; only `is_onboarding_sent` remains editable. `composite_template_id` is write-only; read the saved selection from `composite_program_template` in v2 create/list/detail/update responses. The optional input is also accepted during v2 lead creation.

### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "01a18ad0-7000-7000-8000-000000000002",
    "unique_id": "L-0001",
    "first_name": "Asha",
    "last_name": "Rao",
    "gender": "Female",
    "date_of_birth": "1990-01-01",
    "phone": "+919876543210",
    "email": "asha@example.com",
    "description": "Interested in the wellness package.",
    "is_active": true,
    "is_client": false,
    "is_invited": false,
    "is_joined": false,
    "is_onboarding_sent": false,
    "converted_on": null,
    "packages": [],
    "home_center": {
      "id": "01a18ad0-7000-7000-8000-000000000004",
      "code": "CTR001",
      "name": "Main Center",
      "image": null,
      "address": "Main Road",
      "address_line_1": "Main Road",
      "address_line_2": null,
      "city": "Bengaluru",
      "state": "Karnataka",
      "country": "India",
      "pincode": "560001",
      "staff_count": 5,
      "inactive_staff_count": 0,
      "customer_count": 20,
      "inactive_customer_count": 0,
      "is_active": true,
      "created_at": "2026-11-01T09:00:00+05:30",
      "updated_at": "2026-11-04T09:00:00+05:30"
    },
    "composite_program_template": {
      "id": "01a18ad0-7000-7000-8000-000000000001",
      "code": "WELLNESS",
      "name": "Wellness Package",
      "is_active": true
    },
    "customer_profile": {
      "id": "01a18ad0-7000-7000-8000-000000000003",
      "contact_email": "asha@example.com",
      "phone": "+919876543210",
      "first_name": "Asha",
      "last_name": "Rao",
      "gender": "Female",
      "date_of_birth": "1990-01-01",
      "image": null,
      "is_main": true,
      "is_legacy": false,
      "is_onboarding_sent": false,
      "is_onboarding_completed": false,
      "is_converted": false,
      "is_latest_consent_given": false,
      "created_at": "2026-11-04T09:30:00+05:30",
      "updated_at": "2026-11-04T10:00:00+05:30"
    },
    "created_by": {
      "id": "01a18ad0-7000-7000-8000-000000000005",
      "email": "admin@example.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-11-04T09:00:00+05:30"
    },
    "updated_by": {
      "id": "01a18ad0-7000-7000-8000-000000000005",
      "email": "admin@example.com",
      "first_name": "Admin",
      "last_name": "User",
      "image": null,
      "last_login": "2026-11-04T09:00:00+05:30"
    },
    "created_at": "2026-11-04T09:30:00+05:30",
    "updated_at": "2026-11-04T10:00:00+05:30"
  }
}
```

With no selection, `composite_program_template` is `null`.

### Response — `400 Bad Request`: unavailable template

```json
{
  "detail": {
    "composite_template_id": ["Invalid or inactive composite template."]
  }
}
```

### Response — `400 Bad Request`: edit after conversion

```json
{
  "detail": "Only is_onboarding_sent is allowed to be updated after a lead is converted."
}
```

### Response — `400 Bad Request`: concurrent lead change

```json
{
  "detail": "Lead has changed. Refresh the lead before updating it."
}
```

## 3. Convert and view the program

Use the usual v2 convert-client action; a home center is required. A selected template creates one composite program named after it, with assessment type `baseline` and its active services and quantities. Conversion and assignment succeed or roll back together. No template means no program. Both existing conversion routes apply this same rule.

After success, refresh the existing client-profile composite-programs list to show staff the package. Each therapy service selects the home center when it has an active service assignment there and the center and client-center assignment are active. When at least one service qualifies, the home center is also added to the program's redemption centers. Other service selections remain empty; global therapy redemption stays disabled. Configure remaining centers and metadata later through existing program flows. The lead's assignment stays locked and repeat conversion is rejected; the generated program remains editable.
