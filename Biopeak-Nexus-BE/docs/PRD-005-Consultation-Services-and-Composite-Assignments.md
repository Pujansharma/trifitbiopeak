# Consultation Services, Composite Assignments, and Documents — Frontend ePRD

Manage consultation definitions, include them in composite templates, assign those templates to customer profiles, open each assigned consultation, and upload metadata groups and files.

Use `Authorization: Bearer <token>` for every request. Catalogue writes and template creation are admin-only; their reads also allow associates. Customer assignment requires an admin or an associate with Packages permission. Add-ons and assigned-service listing allow admins or associates with a valid center assignment. Consultation service/document reads and writes require an admin or an associate with center access. For a consultation-only package, follow 2 → 6 → 8 → 9 → 10 or 11 → 12 → 13 → 14. These are staff workflows; assigning a program to a customer does not make these endpoints customer-accessible.

## Logical Flow

1. **Browse consultations** — Find active catalogue definitions for selection or include inactive definitions for administration.
2. **Create a consultation** — Define its name and global or selected-center coverage.
3. **Read a consultation** — Load current catalogue data before editing.
4. **Edit or deactivate a consultation** — Change details, center coverage, or active status by catalogue ID.
5. **List selected centers** — Load explicit center selections beyond the three-item catalogue preview.
6. **Create a composite template** — Attach consultation catalogue IDs without quantities.
7. **List template consultations** — Confirm consultation membership and obtain template-line IDs.
8. **Assign the template to a customer** — Create a composite program for an eligible customer profile.
9. **Get the assigned composite program** — Open the assigned client program and its consultation totals.
10. **List assigned consultations** — Load consultation occurrences for the selected composite program.
11. **List consultations for the client and composite program** — Use the client-profile screen to filter the same occurrences by composite program.
12. **Get the assigned consultation service** — Open one occurrence using its assigned program-service ID.
13. **Create consultation document metadata** — Create a typed and dated group before any file upload.
14. **Upload a file into the metadata group** — Append one binary file per multipart request.
15. **List consultation document metadata** — Refresh the consultation’s groups and per-group file counts.
16. **List files inside a document** — Read files belonging to a selected group.
17. **List files across the consultation service** — Read all files with optional metadata and filename filters.
18. **Add consultations to an existing program** — Optionally add further consultation occurrences without modifying the template.

Catalogue IDs are submitted in `add_services[].id`. Template-line IDs and assigned program-service IDs identify different resources and must not replace catalogue IDs in write payloads. Consultation booking, redemption, pricing per service, and usage/session tracking are outside this phase.

## API Requests

### 1. Browse consultations

Read consultation definitions; results include active and inactive records unless filtered.

**Method:** `GET`

**URL:** `<baseURL>/services/consultation-services/`

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Nutrition` | Trimmed, case-insensitive name substring. |
| `active` | No | `1` | `1` active, `0` inactive; omitted or unsupported values do not filter. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000001",
      "name": "Nutrition Consultation",
      "image": null,
      "is_global": false,
      "is_active": true,
      "centers": [
        {
          "id": "0199e800-0000-7000-8000-000000000002",
          "code": "BLR01",
          "name": "Bengaluru"
        }
      ],
      "centers_count": 1,
      "service_category": "Consultation",
      "service_category_code": "consultation",
      "created_by": {
        "id": "0199e800-0000-7000-8000-000000000008",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-15T10:00:00+05:30"
      },
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    }
  ]
}
```

`centers` previews at most three active assignments. `centers_count` counts explicit active assignments, not dynamic global coverage. Global definitions return `centers: []` and `centers_count: 0`.

### 2. Create a consultation

Create an admin-managed catalogue definition with a server-fixed consultation category.

**Method:** `POST`

**URL:** `<baseURL>/services/consultation-services/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `name` | Yes | `Nutrition Consultation` | Nonblank, maximum 200 characters; unique across all service categories, case-insensitively. |
| `image` | No | `null` | File upload or null to clear; upload using multipart rather than a JSON file path. |
| `is_global` | No | `true` | Default false; true covers all current and future centers. |
| `is_active` | No | `false` | Default true. |
| `add_centers` | Conditional | `[{"id":"<center_uuid>"}]` | Add selections; UUIDs must exist. Accepts null or an empty list. |
| `remove_centers` | No | `[{"id":"<center_uuid>"}]` | Remove selections; UUIDs must exist. Accepts null or an empty list. |
    
```json
{
  "name": "Nutrition Consultation",
  "is_global": false,
  "is_active": true,
  "add_centers": [
    {
      "id": "0199e800-0000-7000-8000-000000000002"
    }
  ]
}
```

At least one resulting center selection is required when `is_global=false`. For a global definition send `is_global=true` and omit center arrays. Parsed center arrays are ignored while global; malformed UUIDs still fail field parsing. `service_category`, counts, timestamps, and `created_by` are read-only.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000001",
    "name": "Nutrition Consultation",
    "image": null,
    "is_global": false,
    "is_active": true,
    "centers": [
      {
        "id": "0199e800-0000-7000-8000-000000000002",
        "code": "BLR01",
        "name": "Bengaluru"
      }
    ],
    "centers_count": 1,
    "service_category": "Consultation",
    "service_category_code": "consultation",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30"
  }
}
```

#### Errors

`400 Bad Request` — duplicate name:

```json
{
  "detail": {
    "name": [
      "A service with this name already exists."
    ]
  }
}
```

`400 Bad Request` — no selected center while global coverage is off:

```json
{
  "detail": {
    "add_centers": "At least one center is required when all centers is off."
  }
}
```

Invalid center IDs return `400` with `detail.add_centers` or `detail.remove_centers`, for example `"Invalid center IDs provided: <uuid>"`.

### 3. Read a consultation

Retrieve the consultation definition for an edit form.

**Method:** `GET`

**URL:** `<baseURL>/services/consultation-services/<service_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `service_id` | Yes | `<service_id>` | Consultation catalogue service ID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000001",
    "name": "Nutrition Consultation",
    "image": null,
    "is_global": false,
    "is_active": true,
    "centers": [
      {
        "id": "0199e800-0000-7000-8000-000000000002",
        "code": "BLR01",
        "name": "Bengaluru"
      }
    ],
    "centers_count": 1,
    "service_category": "Consultation",
    "service_category_code": "consultation",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30"
  }
}
```

#### Errors

`404 Not Found` — unknown ID or ID belonging to another service category:

```json
{
  "detail": "Consultation service not found"
}
```

### 4. Edit or deactivate a consultation

Partially update a consultation definition; omitted fields and center selections are preserved.

**Method:** `PATCH`

**URL:** `<baseURL>/services/consultation-services/<service_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `service_id` | Yes | `<service_id>` | Consultation catalogue service ID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `name` | No | `Nutrition Consultation` | Nonblank, maximum 200 characters; unique across all service categories, case-insensitively. |
| `image` | No | `null` | File upload or null to clear; upload using multipart rather than a JSON file path. |
| `is_global` | No | `true` | All current and future centers. |
| `is_active` | No | `false` | Deactivate or reactivate the definition. |
| `add_centers` | Conditional | `[{"id":"<center_uuid>"}]` | Add selections; UUIDs must exist. Accepts null or an empty list. |
| `remove_centers` | No | `[{"id":"<center_uuid>"}]` | Remove selections; UUIDs must exist. Accepts null or an empty list. |

```json
{
  "is_global": true
}
```

#### Logic

Enabling global coverage clears explicit assignments and ignores parsed center additions/removals. Switching back requires `is_global=false` together with nonempty `add_centers`. Selected-center edits remove before adding, so an ID in both arrays ends up selected. Removing the last selection while non-global fails atomically. Re-adding an inactive assignment reactivates it.

Use `{"is_active":false}` to deactivate. There is no DELETE endpoint. Deactivation does not delete previously assigned customer occurrences; inactive definitions cannot be newly attached or added, and inactive template services are skipped during subsequent program assignment.

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000001",
    "name": "Nutrition Consultation",
    "image": null,
    "is_global": true,
    "is_active": true,
    "centers": [],
    "centers_count": 0,
    "service_category": "Consultation",
    "service_category_code": "consultation",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30"
  }
}
```

Duplicate-name and center errors match create; missing/wrong-category IDs match detail.

### 5. List selected centers

Read the paginated explicit center assignments for a consultation definition.

**Method:** `GET`

**URL:** `<baseURL>/services/<service_id>/centers/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `service_id` | Yes | `<service_id>` | Catalogue service ID; this shared route is not consultation-restricted. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Bengaluru` | Center-name prefix or center-code substring. |
| `active` | No | `1` | Filters the center's active status, not the assignment's status. Omit to include both. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000002",
      "code": "BLR01",
      "name": "Bengaluru"
    }
  ]
}
```

This shared endpoint lists explicit assignment rows, including inactive assignment rows if present. It does not enumerate global coverage; after enabling global coverage it returns an empty list. The example represents a non-global definition before the global edit above.

### 6. Create a composite template

Attach active consultation catalogue definitions when creating a template.

**Method:** `POST`

**URL:** `<baseURL>/programs/composites/templates/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `code` | Yes | `CONSULT-CARE` | Maximum 50 characters; case-insensitive duplicate check. |
| `name` | Yes | `Consultation Care` | Maximum 200 characters. |
| `description` | No | `Consultation support` | May be null or blank. |
| `is_active` | No | `true` | Defaults true. |
| `add_services` | Yes | `[{"id":"<service_uuid>"}]` | Nonempty list; each ID must be an active catalogue service. |
| `add_services[].quantity` | No | `null` | Omit or send null for consultation; any non-null value is rejected. |

For mixed templates, every therapy entry requires a positive integer `quantity`. Missing or null therapy quantities return `400` under `detail.add_services`; assessment quantity behavior is unchanged.

```json
{
  "code": "CONSULT-CARE",
  "name": "Consultation Care",
  "description": "Consultation support",
  "add_services": [
    {
      "id": "0199e800-0000-7000-8000-000000000001"
    }
  ]
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000003",
    "code": "CONSULT-CARE",
    "name": "Consultation Care",
    "description": "Consultation support",
    "assessment_services_count": 0,
    "therapy_services_count": 0,
    "consultation_services_count": 1,
    "services_count": 1,
    "is_active": true,
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    }
  }
}
```

#### Logic

One template line per catalogue service; repeated catalogue IDs are collapsed. Counts reflect consultation membership. The existing template PATCH updates template metadata and ignores `add_services`; it does not attach, replace, or remove service lines. Do not build template membership editing around that PATCH.

#### Errors

`400 Bad Request` — quantity supplied for a consultation:

```json
{
  "detail": {
    "add_services": "Quantity is not supported for consultation service entries. Remove it from positions: 1."
  }
}
```

Invalid/inactive IDs return `400` with `detail.add_services` containing `"Invalid or inactive service IDs provided: <uuid>"`.

### 7. List template consultations

Read consultation membership for a template.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/templates/<template_id>/services/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `template_id` | Yes | `<template_id>` | Composite template ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `consultation` | Send this value to restrict results to consultations. |
| `search` | No | `Nutrition` | Case-insensitive service-name substring. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000007",
      "name": "Nutrition Consultation",
      "quantity": null,
      "is_global": true,
      "service_category": "Consultation",
      "service_category_code": "consultation",
      "image": null,
      "is_active": true,
      "is_locked": false,
      "centers_count": 0,
      "redeemable_centers_count": 0,
      "products": [],
      "products_count": 0,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30",
      "created_by": {
        "id": "0199e800-0000-7000-8000-000000000008",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-15T10:00:00+05:30"
      },
      "prerequisite": null
    }
  ]
}
```

The response `id` identifies the template line. `redeemable_centers_count` is currently zero for consultation lines, including global consultations; use `is_global` to interpret coverage. `is_locked` indicates whether the service appears in any assigned program, not whether this endpoint provides membership editing.

### 8. Assign the template to a customer

Create a composite program containing the template's active consultations.

**Method:** `POST`

**URL:** `<baseURL>/centers/<center_id>/composite-programs/`

Associates must send `X-Center-ID: <center_id>` matching the URL and have Packages permission at that center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `center_id` | Yes | `<center_id>` | Active assigning center; the profile must have an active assignment here. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Active customer profile assigned to the URL center. |
| `composite_template_id` | Yes | `<template_uuid>` | Active template with at least one active service. |
| `expires_at` | Yes | `2027-01-15` | Date, today or later. |
| `redeemable_centers` | Yes | `[{"id":"<center_uuid>"}]` | Nonempty list of active centers actively assigned to this profile. |
| `name` | No | `Consultation Care` | Maximum 200 characters; null/blank allowed, blank becomes null. |
| `notes` | No | `null` | Null or blank allowed. |
| `assessment_type` | Conditional | `null` | Not needed for consultation-only templates; required if active assessment services are included. Choices: `baseline`, `annual`, `six_month_review`, `retest`, `special_investigation`. |
| `is_complimentary` | No | `true` | Defaults true; applies to the whole program. |
| `price` | Conditional | `2500.00` | Required when not complimentary; decimal, 10 digits total and 2 decimal places. |
| `created_date` | No | `2026-10-15` | Defaults to the current local date. |
| `therapy_service_centers` | Conditional | `[{"id":"<therapy_service_uuid>","centers":[{"id":"<center_uuid>"}]}]` | For mixed templates, select therapy service centers; omit for consultation-only templates. |

```json
{
  "profile_id": "0199e800-0000-7000-8000-000000000004",
  "composite_template_id": "0199e800-0000-7000-8000-000000000003",
  "name": "Consultation Care",
  "expires_at": "2027-01-15",
  "redeemable_centers": [
    {
      "id": "0199e800-0000-7000-8000-000000000002"
    }
  ],
  "is_complimentary": true
}
```

#### Logic

Every active template service must be global or available at at least one selected redeemable center. Assignment creates an independent program-service occurrence and consultation extension for each active consultation line, with no consultation quantity. It does not propagate later template membership changes into existing programs.

An active therapy line with a missing or nonpositive stored quantity rejects assignment with `400` under `detail.composite_template_id`, identifying the affected catalogue services. This guard also applies to the legacy profile assignment route; that route otherwise retains its existing coverage, optional-expiry, and permission rules.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000005",
    "uid": "<generated_program_uid>",
    "name": "Consultation Care",
    "assessment_type": null,
    "assessment_type_code": null,
    "profile": {
      "id": "0199e800-0000-7000-8000-000000000004",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
      "first_name": "Ravi",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-04-12",
      "image": null,
      "home_center": null,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    },
    "center": {
      "id": "0199e800-0000-7000-8000-000000000002",
      "code": "BLR01",
      "name": "Bengaluru"
    },
    "composite_template": {
      "id": "0199e800-0000-7000-8000-000000000003",
      "code": "CONSULT-CARE",
      "name": "Consultation Care",
      "is_active": true
    },
    "program_type": "composite",
    "notes": null,
    "expires_at": "2027-01-15",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "BLR01",
        "name": "Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": null,
    "services_count": 1,
    "add_ons_count": 0,
    "assessment_services_count": 0,
    "therapy_services_count": 0,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-15",
    "is_active": true,
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "consultation_documents_count": 0,
    "consultation_files_count": 0
  }
}
```

The create response currently has `services:null`; call step 10 for assigned occurrences. Returned `redeemable_centers` contains `code` and `name` only, while writes require `id`; retain the selected center IDs. `home_center` may be null when the profile was not loaded with its home-center preview.

#### Errors

`400 Bad Request` — consultation unavailable at the selected centers:

```json
{
  "detail": {
    "composite_template_id": "Template services are unavailable at the selected centers: <service_uuid>"
  }
}
```

Other implemented validations return `400` under `detail`: `profile_id` for an unassigned profile, `redeemable_centers` for invalid profile-center selections, `composite_template_id` for an inactive/empty template, and `expires_at` for a past expiry.

### 9. Get the assigned composite program

Read the customer’s assigned composite program and its stored consultation totals.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/programs/<composite_program_id>/`

Staff endpoint; send `X-Center-ID` for center-specific service previews.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_program_id` | Yes | `0199e800-0000-7000-8000-000000000005` | Assigned program ID from step 8. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000005",
    "uid": "<generated_program_uid>",
    "name": "Consultation Care",
    "assessment_type": null,
    "assessment_type_code": null,
    "profile": {
      "id": "0199e800-0000-7000-8000-000000000004",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
      "first_name": "Ravi",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-04-12",
      "image": null,
      "home_center": null,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    },
    "center": {
      "id": "0199e800-0000-7000-8000-000000000002",
      "code": "BLR01",
      "name": "Bengaluru"
    },
    "composite_template": {
      "id": "0199e800-0000-7000-8000-000000000003",
      "code": "CONSULT-CARE",
      "name": "Consultation Care",
      "is_active": true
    },
    "program_type": "composite",
    "notes": null,
    "expires_at": "2027-01-15",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "BLR01",
        "name": "Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": [
      {
        "id": "0199e800-0000-7000-8000-000000000006",
        "service": {
          "id": "0199e800-0000-7000-8000-000000000001",
          "name": "Nutrition Consultation",
          "service_category": "Consultation",
          "service_category_code": "consultation",
          "image": null,
          "centers": null
        },
        "service_assignment_type": "Standalone",
        "service_assignment_type_code": "standalone",
        "sessions_count": null,
        "sessions_used": null,
        "sessions_cancelled": null,
        "redeem_code": null,
        "can_redeem": false,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-15",
        "created_by": {
          "id": "0199e800-0000-7000-8000-000000000008",
          "email": "admin@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-15T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-15T10:00:00+05:30",
        "updated_at": "2026-10-15T10:00:00+05:30",
        "redeemable_centers": [],
        "consultation_documents_count": 0,
        "consultation_files_count": 0
      }
    ],
    "services_count": 1,
    "add_ons_count": 0,
    "assessment_services_count": 0,
    "therapy_services_count": 0,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-15",
    "is_active": true,
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "consultation_documents_count": 0,
    "consultation_files_count": 0
  }
}
```

`services` previews at most three occurrences; use step 10 or 11 for the complete paginated list. The consultation counters count metadata groups and uploaded files separately. Empty groups count; assessment result/document/report/raw counters retain their existing meaning.

### 10. List assigned consultations

Load the complete consultation occurrence list for one composite program.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/programs/<composite_program_id>/services/`

Associates require `X-Center-ID` and an active assignment; results are restricted to accessible programs.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_program_id` | Yes | `<composite_program_id>` | Assigned composite program ID, not a template or catalogue ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `consultation` | Send to return consultation occurrences only. |
| `assignment_type` | No | `add_on` | `add_on` for direct additions, `standalone` for template-assigned occurrences; omit for both. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000006",
      "service": {
        "id": "0199e800-0000-7000-8000-000000000001",
        "name": "Nutrition Consultation",
        "service_category": "Consultation",
        "service_category_code": "consultation",
        "image": null,
        "centers": null
      },
      "service_assignment_type": "Add On",
      "service_assignment_type_code": "add_on",
      "sessions_count": null,
      "sessions_used": null,
      "sessions_cancelled": null,
      "redeem_code": null,
      "can_redeem": false,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "fetch_count": 0,
      "fetch_results_count": 0,
      "fetch_documents_count": 0,
      "fetch_pending_count": 0,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-15",
      "created_by": {
        "id": "0199e800-0000-7000-8000-000000000008",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-15T10:00:00+05:30"
      },
      "is_active": true,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30",
      "redeemable_centers": [],
      "consultation_documents_count": 0,
      "consultation_files_count": 0
    }
  ]
}
```

The top-level item `id` is the assigned program-service ID; `service.id` is the catalogue ID. Consultation session counters and redeem code are null. `can_redeem` is false for consultation occurrences; consultation redemption and booking remain outside this flow.

For a global consultation the nested `service.centers` is null, whereas catalogue `centers` is an empty array. For a non-global consultation this nested preview uses the shared full center representation, including address and count fields; the catalogue response uses only `id`, `code`, and `name`.

This program-specific endpoint has no implemented `active` or `search` filter. The client-profile alternative in step 11 supports consultation occurrences with `service_category=consultation` and a `composite_program` filter.

### 11. List consultations for the client and composite program

Filter the client profile’s assigned service occurrences to one composite program and the consultation category.

**Method:** `GET`

**URL:** `<baseURL>/profiles/<profile_id>/programs/composite-program-services/`

Send `X-Center-ID: <center_id>` for admins and associates. The profile must be active and assigned to that center. Associates also need an active assignment to this profile at the center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `0199e800-0000-7000-8000-000000000004` | Customer profile ID used in step 8. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_program` | No | `0199e800-0000-7000-8000-000000000005` | Send to restrict results to the selected assigned composite program. |
| `service_category` | No | `consultation` | Send consultation for this flow; assessment and therapy are also accepted. |
| `category` | No | `consultation` | Alias for service_category; category takes precedence if both are sent. |
| `assignment_type` | No | `standalone` | standalone or add_on; omit for both. |
| `search` | No | `Nutrition` | Trimmed, case-insensitive service-name substring. |
| `active` | No | `1` | 1 active, 0 inactive; omitted returns both. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

For this flow use `?composite_program=<composite_program_id>&service_category=consultation`.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000006",
      "composite_program": {
        "id": "0199e800-0000-7000-8000-000000000005",
        "uid": "<generated_program_uid>",
        "name": "Consultation Care",
        "template": {
          "id": "0199e800-0000-7000-8000-000000000003",
          "code": "CONSULT-CARE",
          "name": "Consultation Care",
          "is_active": true
        }
      },
      "service": {
        "id": "0199e800-0000-7000-8000-000000000001",
        "name": "Nutrition Consultation",
        "service_category": "Consultation",
        "service_category_code": "consultation",
        "image": null,
        "centers": null
      },
      "redeemable_centers": [],
      "assignment_type": "Standalone",
      "assignment_type_code": "standalone",
      "sessions_count": null,
      "sessions_used": null,
      "sessions_cancelled": null,
      "redeem_code": null,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "can_redeem": false,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-15",
      "created_by": {
        "id": "0199e800-0000-7000-8000-000000000008",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-15T10:00:00+05:30"
      },
      "is_active": true,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    }
  ]
}
```

Use each item’s top-level `id` for step 12. `service.id` identifies the catalogue definition. This profile-list serializer does not expose the new consultation counters; read them from step 9, 10, or 12. Invalid declared filter values return 400; an unavailable center/profile returns 404.

### 12. Get the assigned consultation service

Read the consultation occurrence belonging to the selected client’s composite program.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/`

Admins are allowed; associates require `X-Center-ID`, an active center assignment, and program access through its owning or redeemable center. The program-service UUID from step 10 or 11 identifies the occurrence; this URL has no separate profile or composite-program parameter.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `0199e800-0000-7000-8000-000000000006` | Assigned consultation occurrence ID; never the catalogue or template-line ID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000006",
    "program": {
      "id": "0199e800-0000-7000-8000-000000000005",
      "uid": "<generated_program_uid>",
      "profile": {
        "id": "0199e800-0000-7000-8000-000000000004",
        "contact_email": "client@example.com",
        "phone": "+91-9876543210",
        "first_name": "Ravi",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-04-12",
        "image": null,
        "created_at": "2026-10-15T10:00:00+05:30",
        "updated_at": "2026-10-15T10:00:00+05:30",
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": false
      },
      "program_type": "Composite",
      "notes": null,
      "expires_at": "2027-01-15",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 1,
      "sessions_count": null,
      "sessions_used": null,
      "sessions_cancelled": null,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "created_date": "2026-10-15",
      "cancelled_date": null,
      "is_active": true,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    },
    "service": {
      "id": "0199e800-0000-7000-8000-000000000001",
      "name": "Nutrition Consultation",
      "service_category": "Consultation",
      "service_category_code": "consultation",
      "image": null,
      "centers": null
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "consultation_documents_count": 0,
    "consultation_files_count": 0,
    "is_active": true,
    "created_date": "2026-10-15",
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

The nested `program.id` identifies the assigned composite program. Its `program_type` is the display label `Composite`; the composite program endpoints return the code `composite`. An unavailable or out-of-center occurrence returns 404.

### 13. Create consultation document metadata

Create an empty file group under the assigned consultation occurrence.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/documents/`

Uses the same staff and center access as step 12.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `0199e800-0000-7000-8000-000000000006` | Assigned consultation service from step 12. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | Yes | `consultation_notes` | questionnaire → Questionnaire Responses; consultation_notes → Consultation Notes; post_consultation → Post Consultation Notes. |
| `consultation_type` | No | `baseline` | baseline → Baseline; followups → Followups. Defaults to baseline. |
| `consultation_date` | No | `2026-10-23` | Defaults to current local date. Historical dates allowed; future dates rejected. |

```json
{
  "document_type": "consultation_notes",
  "consultation_type": "baseline",
  "consultation_date": "2026-10-23"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000009",
    "document_type": "Consultation Notes",
    "document_type_code": "consultation_notes",
    "consultation_type": "Baseline",
    "consultation_type_code": "baseline",
    "consultation_date": "2026-10-23",
    "files_count": 0,
    "is_active": true,
    "created_at": "2026-10-23T10:05:00+05:30",
    "updated_at": "2026-10-23T10:05:00+05:30"
  }
}
```

Save `data.id` as the document ID for step 14. Repeated type/date combinations create independent groups. Parent ownership, counters, status, and timestamps are server-managed. There is no file in this request. Creation increments the service and composite consultation document counts even before any file exists.

#### Errors

`400 Bad Request` — future consultation date:

```json
{
  "detail": {
    "consultation_date": [
      "Consultation date cannot be in the future."
    ]
  }
}
```

`400 Bad Request` — inactive program/service:

```json
{
  "detail": "Inactive or cancelled consultations are read only."
}
```

`400 Bad Request` — program expiry is earlier than the current local date:

```json
{
  "detail": "Expired consultation programs are read only."
}
```

Expiry today remains writable. The same program/service status and expiry checks apply to uploads, metadata edits, and deletions; reads remain available. An unavailable or inaccessible parent returns 404.

### 14. Upload a file into the metadata group

Append one file to the document group created in step 13.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/consultation-documents/<document_id>/files/`

Use `multipart/form-data`; let the browser generate the boundary. Uses the same staff and center access as step 12.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_id` | Yes | `0199e800-0000-7000-8000-000000000009` | Metadata group UUID from step 13. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `file` | Yes | Binary file | One nonempty file; select File for this field in Postman. |

The JSON below describes the form-data field; transmit the binary as multipart, not as JSON or a file-path string.

```json
{
  "file": "<binary file>"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000010",
    "document": "0199e800-0000-7000-8000-000000000009",
    "file": "<file_url>",
    "filename": "consultation-notes.pdf",
    "content_type": "application/pdf",
    "is_active": true,
    "created_at": "2026-10-23T10:06:00+05:30",
    "updated_at": "2026-10-23T10:06:00+05:30"
  }
}
```

The backend captures the basename and declared content type, uses `application/octet-stream` when absent, and calculates SHA-256 internally. Do not send filename, content_type, file_hash, or document ownership fields. Identical content is allowed and creates another file row. No additional file-type or size policy is imposed beyond standard file-field/infrastructure handling.

Each upload increments document `files_count`, service `consultation_files_count`, and composite `consultation_files_count`. Metadata-group totals stay unchanged. Upload queued files individually, retry only failed uploads, then refresh steps 9, 12, and 15–17 as needed. There is no finalize request.

Invalid/empty file input returns 400. The program/service status and expiry errors from step 13 also apply; an unavailable or inaccessible document returns 404.

### 15. List consultation document metadata

Read the metadata groups and file counts for one assigned consultation.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/documents/`

Uses the same staff and center access as step 12.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `0199e800-0000-7000-8000-000000000006` | Assigned consultation occurrence ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | No | `consultation_notes` | Exact: questionnaire, consultation_notes, post_consultation. |
| `consultation_type` | No | `baseline` | Exact: baseline or followups. |
| `consultation_date` | No | `2026-10-23` | Exact ISO date, YYYY-MM-DD. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000009",
      "document_type": "Consultation Notes",
      "document_type_code": "consultation_notes",
      "consultation_type": "Baseline",
      "consultation_type_code": "baseline",
      "consultation_date": "2026-10-23",
      "files_count": 1,
      "is_active": true,
      "created_at": "2026-10-23T10:05:00+05:30",
      "updated_at": "2026-10-23T10:05:00+05:30"
    }
  ]
}
```

Results are newest first, with no embedded files. Send type codes as filters and read display labels with their `_code` fields. Invalid declared filter values return 400.

### 16. List files inside a document

Read all uploaded files belonging to one metadata group.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-documents/<document_id>/files/`

Uses the same staff and center access as step 12.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_id` | Yes | `0199e800-0000-7000-8000-000000000009` | Metadata group ID, not the program-service ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | No | `consultation_notes` | Exact: questionnaire, consultation_notes, post_consultation. |
| `consultation_type` | No | `baseline` | Exact: baseline or followups. |
| `consultation_date` | No | `2026-10-23` | Exact ISO date, YYYY-MM-DD. |
| `search` | No | `notes` | Case-insensitive filename substring. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000010",
      "document": "0199e800-0000-7000-8000-000000000009",
      "file": "<file_url>",
      "filename": "consultation-notes.pdf",
      "content_type": "application/pdf",
      "is_active": true,
      "created_at": "2026-10-23T10:06:00+05:30",
      "updated_at": "2026-10-23T10:06:00+05:30"
    }
  ]
}
```

Type/date filters apply to the parent metadata group. Results are newest first. Invalid declared filter values return 400.

### 17. List files across the consultation service

Read a service-wide file list without first choosing a metadata group.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/files/`

Uses the same staff and center access as step 12.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `0199e800-0000-7000-8000-000000000006` | Assigned consultation occurrence ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | No | `consultation_notes` | Exact: questionnaire, consultation_notes, post_consultation. |
| `consultation_type` | No | `baseline` | Exact: baseline or followups. |
| `consultation_date` | No | `2026-10-23` | Exact ISO date, YYYY-MM-DD. |
| `document` | No | `0199e800-0000-7000-8000-000000000009` | Limit to a metadata group inside this service. |
| `search` | No | `notes` | Case-insensitive filename substring. |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "0199e800-0000-7000-8000-000000000010",
      "document": "0199e800-0000-7000-8000-000000000009",
      "file": "<file_url>",
      "filename": "consultation-notes.pdf",
      "content_type": "application/pdf",
      "is_active": true,
      "created_at": "2026-10-23T10:06:00+05:30",
      "updated_at": "2026-10-23T10:06:00+05:30"
    }
  ]
}
```

Results are newest first. Invalid declared filter values return 400; a valid document UUID belonging to a different service produces no matching files.

### 18. Add consultations to an existing program

Create further consultation occurrences without modifying the composite template.

**Method:** `POST`

**URL:** `<baseURL>/programs/composites/add-ons/`

Associates require `X-Center-ID` and an active assignment to that center; the program must be owned by or redeemable at an accessible center. The header is optional for admins.

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_program_id` | Yes | `<composite_program_uuid>` | Existing active, non-expired composite program. |
| `add_services` | Yes | `[{"id":"<service_uuid>"}]` | Nonempty list of active catalogue service IDs. |
| `add_services[].sessions_count` | No | `null` | Omit or send null for consultation; non-null values are rejected. Do not submit `quantity`. |

```json
{
  "composite_program_id": "0199e800-0000-7000-8000-000000000005",
  "add_services": [
    {
      "id": "0199e800-0000-7000-8000-000000000001"
    }
  ]
}
```

#### Logic

The consultation must be global or available at at least one active redeemable center of this program. Repeated IDs create separate occurrences, including when the same catalogue service already exists in the program. Every new occurrence uses `assignment_type=add_on`; program pricing remains unchanged. All additions are atomic.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "0199e800-0000-7000-8000-000000000005",
    "uid": "<generated_program_uid>",
    "name": "Consultation Care",
    "assessment_type": null,
    "assessment_type_code": null,
    "profile": {
      "id": "0199e800-0000-7000-8000-000000000004",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
      "first_name": "Ravi",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-04-12",
      "image": null,
      "home_center": null,
      "created_at": "2026-10-15T10:00:00+05:30",
      "updated_at": "2026-10-15T10:00:00+05:30"
    },
    "center": {
      "id": "0199e800-0000-7000-8000-000000000002",
      "code": "BLR01",
      "name": "Bengaluru"
    },
    "composite_template": {
      "id": "0199e800-0000-7000-8000-000000000003",
      "code": "CONSULT-CARE",
      "name": "Consultation Care",
      "is_active": true
    },
    "program_type": "composite",
    "notes": null,
    "expires_at": "2027-01-15",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "BLR01",
        "name": "Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": [
      {
        "id": "0199e800-0000-7000-8000-000000000006",
        "service": {
          "id": "0199e800-0000-7000-8000-000000000001",
          "name": "Nutrition Consultation",
          "service_category": "Consultation",
          "service_category_code": "consultation",
          "image": null,
          "centers": null
        },
        "service_assignment_type": "Add On",
        "service_assignment_type_code": "add_on",
        "sessions_count": null,
        "sessions_used": null,
        "sessions_cancelled": null,
        "redeem_code": null,
        "can_redeem": false,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-15",
        "created_by": {
          "id": "0199e800-0000-7000-8000-000000000008",
          "email": "admin@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-15T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-15T10:00:00+05:30",
        "updated_at": "2026-10-15T10:00:00+05:30",
        "redeemable_centers": [],
        "consultation_documents_count": 0,
        "consultation_files_count": 0
      },
      {
        "id": "0199e800-0000-7000-8000-000000000009",
        "service": {
          "id": "0199e800-0000-7000-8000-000000000001",
          "name": "Nutrition Consultation",
          "service_category": "Consultation",
          "service_category_code": "consultation",
          "image": null,
          "centers": null
        },
        "service_assignment_type": "Standalone",
        "service_assignment_type_code": "standalone",
        "sessions_count": null,
        "sessions_used": null,
        "sessions_cancelled": null,
        "redeem_code": null,
        "can_redeem": false,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-15",
        "created_by": {
          "id": "0199e800-0000-7000-8000-000000000008",
          "email": "admin@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-15T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-15T10:00:00+05:30",
        "updated_at": "2026-10-15T10:00:00+05:30",
        "redeemable_centers": [],
        "consultation_documents_count": 0,
        "consultation_files_count": 0
      }
    ],
    "services_count": 2,
    "add_ons_count": 1,
    "assessment_services_count": 0,
    "therapy_services_count": 0,
    "consultation_services_count": 2,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-15",
    "is_active": true,
    "created_at": "2026-10-15T10:00:00+05:30",
    "updated_at": "2026-10-15T10:00:00+05:30",
    "created_by": {
      "id": "0199e800-0000-7000-8000-000000000008",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-15T10:00:00+05:30"
    },
    "consultation_documents_count": 0,
    "consultation_files_count": 0
  }
}
```

`services` previews at most three occurrences; call step 10 for the complete list. The example contains the new add-on and the existing template-assigned occurrence.

#### Errors

`400 Bad Request` — consultation session count supplied:

```json
{
  "detail": {
    "add_services": "Quantity is only supported for therapy service entries. Remove it from positions: 1."
  }
}
```

`400 Bad Request` — consultation unavailable:

```json
{
  "detail": {
    "add_services": "Consultation services are unavailable at the program's redeemable centers: <service_uuid>."
  }
}
```

Invalid/inactive/unsupported catalogue IDs return `400` with `detail.add_services`. Invalid, inactive/cancelled, or expired programs return `400` with `detail.composite_program_id`.

