# Program Payments — Frontend ePRD

Record receipts for therapy and composite programs and list a program's payment history.

## Logical Flow

1. **Edit program details** — Set the program's price and credit/complimentary status through its update endpoint.
2. **Record a receipt** — Submit the newly received amount and optional receipt notes for a therapy or composite program. Stored program status determines eligibility.
3. **List payment history** — Read the program's recorded receipts, newest first.

Admins may access both APIs. Associates require `X-Center-ID` with active center RBAC access, and the program must
belong to an active center where they have an active assignment or be redeemable at such a center. Customers cannot
access these APIs. Existing clients do not need to migrate their result, request, or consultation-document URLs.

## API Requests

### 1. Record a receipt

Add a newly received amount to a therapy or composite program and record its receipt.

**Method:** `POST`

**Therapy URL:** `<baseURL>/programs/therapy-programs/<program_id>/payments/`

**Composite URL:** `<baseURL>/programs/composites/programs/<program_id>/payments/`

#### Path Parameters

| Name         | Required | Example          | Notes                                           |
|--------------|----------|------------------|-------------------------------------------------|
| `program_id` | Yes      | `<program_uuid>` | Therapy or composite program ID; also the parent Program ID. |

#### Payload

| Name              | Required | Example     | Notes                                                                            |
|-------------------|----------|-------------|----------------------------------------------------------------------------------|
| `amount_received` | Yes      | `"2000.00"` | Positive decimal with at most 10 total digits and 2 decimal places; minimum `0.01`. The new paid total cannot exceed program price. |
| `notes` | No | `"Received by bank transfer."` | Receipt-specific text. May be omitted, blank, or null; omission stores null. |
| `is_credit` | No | `true` | Accepted for compatibility but ignored. Eligibility uses stored program status; this endpoint does not change it. |
| `is_complimentary` | No | `false` | Accepted for compatibility but ignored. Cannot override the stored complimentary status. |

```json
{
  "amount_received": "2000.00",
  "notes": "Received by bank transfer.",
  "is_credit": true,
  "is_complimentary": false
}
```

#### Logic

Each successful POST creates one payment-history record and adds `amount_received` to the existing
`Program.credit_received` in one transaction. A null existing total is treated as zero. Existing totals are preserved;
no historical receipts are backfilled. For example, a total of `1000.00` followed by receipts of `2000.00` and `500.00`
becomes `3500.00`, with two new history records, provided the program price permits each payment.
Repeating a POST records another receipt subject to the same price cap; there is no duplicate-request suppression.

`notes` is stored on the payment-history record and returned in both the receipt POST response and each payment-history
item. It does not change the Program's own notes. The response value is a string or null; blank and null remain distinct.

Both payment routes use the stored program state, regardless of any flags in the payload:

- A complimentary program cannot receive payments, even if it has a stored price.
- A non-complimentary program requires a non-null price.
- The existing `credit_received` plus `amount_received` cannot exceed price. Exact settlement is allowed.
- Every accepted payment increments `credit_received`, including for regular programs with `is_credit=false`.

The supplied flags are discarded; neither stored flag is updated or audited. Change status through the program
update endpoint before making a payment. The receipt total increment itself is not audited. The authenticated
staff user is recorded as the receipt's `created_by`. Read the program detail to obtain its flags and total.

The total increment and receipt are committed in one transaction. The database update checks current eligibility
and the price cap to prevent concurrent receipts from exceeding price. A failed payment creates no receipt and
does not change the total. A concurrent program change may require refreshing and retrying the request.
Existing totals and history remain intact when price or status changes through program editing; a later payment
is subject to the current stored status and price.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<payment_uuid>",
    "amount_received": "2000.00",
    "notes": "Received by bank transfer.",
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "created_at": "2026-10-24T10:00:00+05:30"
  }
}
```

#### Errors

`400 Bad Request` — Required amount omitted:

```json
{
  "detail": {
    "amount_received": [
      "This field is required."
    ]
  }
}
```

`400 Bad Request` — The stored program is complimentary, regardless of submitted flags:

```json
{
  "detail": "Cannot make a payment against complimentary program."
}
```

`400 Bad Request` — The stored program is non-complimentary but has no price:

```json
{
  "detail": "Program does not have price."
}
```

`400 Bad Request` — The payment would exceed program price:

```json
{
  "detail": {
    "amount_received": "Total amount paid cannot exceed the program price."
  }
}
```

`400 Bad Request` — Zero or negative amounts are rejected by the amount field's minimum-value validation.

`404 Not Found` — The program is unavailable, outside the associate's scope, or does not match the route's program type:

```json
{
  "detail": "Program not found."
}
```

### 2. List payment history

List the program's recorded receipts with staff attribution and timestamps.

**Method:** `GET`

**URL:** `<baseURL>/programs/<program_id>/payment-history/`

#### Path Parameters

| Name         | Required | Example          | Notes              |
|--------------|----------|------------------|--------------------|
| `program_id` | Yes      | `<program_uuid>` | Parent Program ID. |

#### Query Parameters

| Name    | Required | Example | Notes                     |
|---------|----------|---------|---------------------------|
| `page`  | No       | `1`     | Default: 1.               |
| `limit` | No       | `10`    | Default: 10; maximum: 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<payment_uuid>",
      "amount_received": "2000.00",
      "notes": "Received by bank transfer.",
      "created_by": {
        "id": "<user_uuid>",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": null
      },
      "created_at": "2026-10-24T10:00:00+05:30"
    }
  ]
}
```

Items are ordered by `created_at` descending, then ID descending. `created_by` may be null if the user was deleted.
An accessible program with no recorded receipts returns `count: 0` and `data: []`. An unavailable or out-of-scope
program returns `404` with `{"detail": "Program not found."}`.

## Program editing

`PUT` and `PATCH <baseURL>/programs/composites/programs/<program_id>/` accept `name`, `expires_at`, `notes`,
`price`, `is_credit`, and `is_complimentary`. Omitted fields retain their stored values. Name is stored on the
composite; the other fields are stored on its parent Program. Name and notes may be blank or null, and expiry may
be null. A supplied expiry date cannot be earlier than today. Both flags cannot be true; the resulting
non-complimentary state requires a price. Existing redemption-center editing remains available.

Financial edits are allowed regardless of existing payments: price may be reduced below the paid total, or the
program may be changed to complimentary. Neither action clears the paid total or receipts. Future payments must
meet the stored-status and price-cap rules above.

The existing `PATCH <baseURL>/programs/therapy-programs/<program_id>/` also accepts `price`, `is_credit`, and
`is_complimentary` under its existing merged-state rules. `credit_received` remains read-only on both program
update endpoints; switching to credit does not require supplying a credit amount. Use receipt POST only to add
newly received amounts. Assigned therapy-service PATCH also accepts top-level flags for its standalone or
composite parent program without creating a receipt.
Program creation remains unchanged and still accepts its existing flag and initial credit-amount inputs.
Payment history contains only receipts recorded through the new POST.

The existing payment-history model and nullable `notes` field must already be migrated. Adding the composite
payment route, changing payment validation, and enabling composite edits require no additional model changes or migrations.
