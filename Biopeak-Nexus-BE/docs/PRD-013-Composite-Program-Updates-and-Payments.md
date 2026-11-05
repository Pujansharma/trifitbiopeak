# Composite Program Updates and Payments — ePRD

Authenticated endpoints use Bearer tokens.

## Logical Flow

1. **Update composite program** — Edit program details, price, or financial status.
2. **Record composite payment** — Add a receipt against the program's stored price and status.

Admins and associates can use these endpoints; customers cannot. Associates send `X-Center-ID: <center_uuid>`.
Composite detail, updates, and payments require an active center assignment and a program owned by or redeemable at an active assigned center.

## 1. Update composite program

PATCH (Authenticated): `<baseURL>/programs/composites/programs/<program_id>/`

### Params

| Name         | In   | Required | Description                                           |
|--------------|------|----------|-------------------------------------------------------|
| `program_id` | path | Yes      | Composite program UUID; also its parent Program UUID. |

### Payload — updated fields

| Field              | Required                                  | Description                                                     |
|--------------------|-------------------------------------------|-----------------------------------------------------------------|
| `name`             | No                                        | Text, maximum 200 characters; blank/null allowed.               |
| `expires_at`       | No                                        | `YYYY-MM-DD`, today or later; null clears expiry.               |
| `notes`            | No                                        | Text; blank/null allowed.                                       |
| `price`            | If non-complimentary with no stored price | Decimal, 10 digits/2 decimals; null allowed when complimentary. |
| `is_credit`        | No                                        | Boolean; cannot be true together with complimentary.            |
| `is_complimentary` | No                                        | Boolean; false requires a supplied or stored price.             |

Omitted values remain unchanged; `credit_received` is read-only. Editing price/status never clears receipts or paid
totals,
and may reduce price below the paid total or switch the program to complimentary. Center discovery, additions, and
coverage rules are
documented separately in [Composite Therapy Management](PRD-014-Composite-Therapy-Management.md).

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
      "home_center": null,
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
    "notes": "Updated program notes.",
    "expires_at": "2027-11-02",
    "is_complimentary": false,
    "is_credit": true,
    "credit_received": "1000.00",
    "price": "5000.00",
    "redeemable_centers": [],
    "therapy_redemption_is_global": true,
    "redeemable_centers_count": 0,
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

**400 — both resulting flags true:**

```json
{
  "detail": {
    "is_credit": "A program cannot be both complimentary and credit."
  }
}
```

**400 — resulting non-complimentary program without price:**

```json
{
  "detail": {
    "price": "Price is required when program is not complimentary."
  }
}
```

**400 — supplied expiry is in the past:**

```json
{
  "detail": {
    "expires_at": "Expiry date cannot be earlier than today's date."
  }
}
```

## 2. Record composite payment

POST (Authenticated): `<baseURL>/programs/composites/programs/<program_id>/payments/`

### Params

| Name         | In   | Required | Description                                           |
|--------------|------|----------|-------------------------------------------------------|
| `program_id` | path | Yes      | Composite program UUID; also its parent Program UUID. |

### Payload

| Field              | Required | Description                                                  |
|--------------------|----------|--------------------------------------------------------------|
| `amount_received`  | Yes      | Decimal, minimum `0.01`; 10 digits/2 decimals.               |
| `notes`            | No       | Receipt notes; blank/null allowed; omission stores null.     |
| `is_credit`        | No       | Boolean, accepted but ignored; never updates program status. |
| `is_complimentary` | No       | Boolean, accepted but ignored; never updates program status. |

Stored complimentary status blocks payment even if price exists; a non-complimentary program requires price.
Each successful POST creates a receipt and increments `credit_received` (null starts at zero), including when stored
`is_credit=false`.
The new total cannot exceed price; exact settlement is allowed. Failures change nothing. Repeating a successful request
records another receipt.
Receipt notes do not change program notes; payment never updates either status flag.

### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<payment_uuid>",
    "amount_received": "2000.00",
    "notes": "Received by bank transfer.",
    "created_by": {
      "id": "<staff_uuid>",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "created_at": "2026-11-02T10:05:00+05:30"
  }
}
```

**400 — stored program is complimentary:**

```json
{
  "detail": "Cannot make a payment against complimentary program."
}
```

**400 — stored program has no price:**

```json
{
  "detail": "Program does not have price."
}
```

**400 — total would exceed price:**

```json
{
  "detail": {
    "amount_received": "Total amount paid cannot exceed the program price."
  }
}
```

**400 — zero or negative amount:**

```json
{
  "detail": {
    "amount_received": [
      "Ensure this value is greater than or equal to 0.01."
    ]
  }
}
```

**400 — concurrent program change; refresh before retrying:**

```json
{
  "detail": "Program changed while recording payment. Please retry."
}
```
