# Composite Therapy Management — ePRD

Authenticated endpoints use Bearer tokens.

## Logical Flow

1. **List available redemption centers** — Load customer-linked and already-selected program centers for the picker.
2. **Add program redemption centers** — Append selected centers and optionally change therapy coverage mode.

Admins and associates can use these endpoints; customers cannot. Associates send `X-Center-ID: <center_uuid>`.
The center picker requires an active associate assignment to that center and a composite owned by or redeemable at that
center.
Metadata editing and payments are documented
in [Composite Program Updates and Payments](PRD-013-Composite-Program-Updates-and-Payments.md).

## 1. List available redemption centers

GET (Authenticated): `<baseURL>/programs/composites/programs/<program_id>/available-redeemable-centers/`

### Params

| Name         | In    | Required | Description                                                          |
|--------------|-------|----------|----------------------------------------------------------------------|
| `program_id` | path  | Yes      | Composite program UUID; also its parent Program UUID.                |
| `active`     | query | No       | `1`: active centers; `0`: inactive. Omitted/invalid defaults to `1`. |
| `search`     | query | No       | Trimmed name substring or code prefix; case-insensitive.             |
| `page`       | query | No       | Page number; default `1`.                                            |
| `limit`      | query | No       | Page size; default `10`, maximum `50`.                               |

The list is the deduplicated union of the program customer's profile centers and stored program redemption centers,
filtered by center status. `exists=true` means the center is already selected on the program, even if no longer
linked to the customer. `is_home_center` identifies the profile's primary assignment. Assignment active status does
not filter discovery; additions still require active customer assignments. The profile comes from the program,
not a supplied profile ID. Order: home center first, then selected centers, then newest center and UUID first.

### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<center_uuid>",
      "code": "CTR001",
      "name": "Main Center",
      "exists": false,
      "is_home_center": true
    }
  ]
}
```

Select `data[].id` for additions. Load remaining pages as needed. An empty matching union returns `count: 0` and
`data: []`.

**404 — missing composite or outside associate scope:**

```json
{
  "detail": "Composite program not found."
}
```

## 2. Add program redemption centers

PATCH (Authenticated): `<baseURL>/programs/composites/programs/<program_id>/`

### Params

| Name         | In   | Required | Description                                           |
|--------------|------|----------|-------------------------------------------------------|
| `program_id` | path | Yes      | Composite program UUID; also its parent Program UUID. |

### Payload — center management

| Field                          | Required      | Description                                                                       |
|--------------------------------|---------------|-----------------------------------------------------------------------------------|
| `add_redeemable_centers`       | No            | Array of center references; empty/omitted adds nothing.                           |
| `add_redeemable_centers[].id`  | Yes per entry | Active center UUID with active customer-profile assignment.                       |
| `therapy_redemption_is_global` | No            | Boolean; omitted preserves mode. Explicit mode updates require a therapy service. |

Stored centers are unioned with additions: `{A, B}` plus `{B, C}` becomes `{A, B, C}`. Duplicate/repeated additions
do not duplicate assignments or create unchanged-center audit entries. Parent additions do not require a therapy
service. `redeemable_centers` is response-only; send additions through `add_redeemable_centers`, not that field.
This operation does not remove centers or change service selections. Successful additions refresh the center count
and audit changed membership atomically. Invalid requests change nothing. Refresh the picker after success.

Coverage uses the existing redemption rules:

- **Global:** ignores the parent-center restriction. Explicit service selections still constrain redemption;
  a service with no selected centers uses the existing active-customer-center/catalogue-availability fallback.
- **Scoped:** requires a nonempty resulting parent set. Effective centers are the intersection of service selections,
  parent program centers, active customer assignments, active centers, and active catalogue assignments.
- Switching to scoped keeps service selections outside the parent set; those centers simply do not qualify for
  redemption. For example, parent `{A, B}` and service selections `{B, C}` permit only `B` when otherwise eligible.

Adding parent centers never switches global mode automatically or expands individual service selections. Existing
service `add_centers` handling remains unchanged; use the assigned service's existing center-management endpoint:
`/programs/program-services/therapy-services/<program_service_id>/redeemable-centers/`.
Lifecycle, expiry, and remaining-session eligibility checks continue to apply.

### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "<program_uuid>",
    "uid": "P0100",
    "name": "Wellness Program",
    "assessment_type": null,
    "assessment_type_code": null,
    "profile": {
      "id": "<profile_uuid>",
      "contact_email": "client@example.com",
      "phone": "+919876543210",
      "first_name": "Asha",
      "last_name": "Rao",
      "gender": "Female",
      "date_of_birth": "1990-01-01",
      "image": null,
      "home_center": {
        "id": "<center_uuid>",
        "code": "CTR001",
        "name": "Main Center"
      },
      "created_at": "2026-11-01T10:00:00+05:30",
      "updated_at": "2026-11-01T10:00:00+05:30"
    },
    "center": {
      "id": "<center_uuid>",
      "code": "CTR001",
      "name": "Main Center"
    },
    "composite_template": {
      "id": "<template_uuid>",
      "code": "WELLNESS",
      "name": "Wellness",
      "is_active": true
    },
    "program_type": "composite",
    "notes": null,
    "expires_at": "2027-11-02",
    "is_complimentary": false,
    "is_credit": true,
    "credit_received": "1000.00",
    "price": "5000.00",
    "redeemable_centers": [
      {
        "id": "<center_uuid>",
        "code": "CTR001",
        "name": "Main Center"
      }
    ],
    "therapy_redemption_is_global": false,
    "redeemable_centers_count": 1,
    "services_count": 1,
    "add_ons_count": 0,
    "assessment_services_count": 0,
    "therapy_services_count": 1,
    "consultation_services_count": 0,
    "consultation_documents_count": 0,
    "consultation_files_count": 0,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-11-01",
    "is_active": true,
    "created_at": "2026-11-01T10:00:00+05:30",
    "updated_at": "2026-11-02T10:00:00+05:30",
    "created_by": null
  }
}
```

**400 — a submitted center is inactive, unassigned, or has an inactive customer assignment:**

```json
{
  "detail": {
    "add_redeemable_centers": "Select active customer centers."
  }
}
```

**400 — explicit scoped mode without any resulting parent center:**

```json
{
  "detail": {
    "add_redeemable_centers": "Select redemption centers."
  }
}
```

**400 — explicit mode update without a therapy service:**

```json
{
  "detail": "Therapy coverage requires a therapy service."
}
```
