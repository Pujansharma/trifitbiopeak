# Program Payments — Frontend ePRD

Record receipts for therapy programs and list a program's payment history.

## Logical Flow

1. **Record a receipt** — Submit the newly received amount, optional receipt notes, and optional credit/complimentary flags for a therapy program.
2. **List payment history** — Read the program's recorded receipts, newest first.

Admins may access both APIs. Associates require `X-Center-ID` with active center RBAC access, and the program must
belong to an active center where they have an active assignment or be redeemable at such a center. Customers cannot
access these APIs. Existing clients do not need to migrate their result, request, or consultation-document URLs.

## API Requests

### 1. Record a receipt

Add a newly received amount to the therapy program and record its receipt.

**Method:** `POST`

**URL:** `<baseURL>/programs/therapy-programs/<program_id>/payments/`

#### Path Parameters

| Name         | Required | Example          | Notes                                           |
|--------------|----------|------------------|-------------------------------------------------|
| `program_id` | Yes      | `<program_uuid>` | Therapy program ID; also the parent Program ID. |

#### Payload

| Name              | Required | Example     | Notes                                                                            |
|-------------------|----------|-------------|----------------------------------------------------------------------------------|
| `amount_received` | Yes      | `"2000.00"` | Decimal with at most 10 total digits and 2 decimal places. A new receipt amount. |
| `notes` | No | `"Received by bank transfer."` | Receipt-specific text. May be omitted, blank, or null; omission stores null. |
| `is_credit` | No | `true` | Boolean. Omission retains the stored value. Cannot be true with the resulting `is_complimentary=true`. |
| `is_complimentary` | No | `false` | Boolean. Omission retains the stored value. A resulting non-complimentary program requires an existing price. |

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
becomes `3500.00`, with two new history records. Repeating a POST records another receipt.

`notes` is stored on the payment-history record and returned in both the receipt POST response and each payment-history
item. It does not change the Program's own notes. The response value is a string or null; blank and null remain distinct.

Supplied flags update the Program, not the receipt. Omitted flags retain their stored values, and explicit `false`
is applied. When either flag is supplied, the resulting combination is validated: both cannot be true; credit and
regular paid programs require an existing non-null price. Set that price through program PATCH before recording a
receipt that switches a program from complimentary to credit or regular paid. Complimentary is
`is_complimentary=true, is_credit=false`; credit is `false, true`; regular paid is `false, false`. There is no `is_paid`
field. Amount-only requests retain their existing behavior.

Flag changes, the total increment, the receipt, and one audit entry per changed flag are committed in the same
transaction. Unchanged flags create no audit entries, and the receipt total increment itself is not audited.
Invalid flags create no receipt, total change, flag change, or audit entry. This API does not compare receipts with
price or derive classification flags from totals. The authenticated staff user is recorded as `created_by` on the
receipt and flag audit entries. The flags are request-only here; receipt and payment-history responses include the
receipt's `notes`. Read the therapy program detail to obtain its current flags and total.

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

`400 Bad Request` — Both resulting flags are true:

```json
{
  "detail": {
    "is_credit": "A program cannot be both complimentary and credit."
  }
}
```

`400 Bad Request` — A supplied flag produces a non-complimentary program without a stored price:

```json
{
  "detail": {
    "price": "Price is required when program is not complimentary."
  }
}
```

`404 Not Found` — The program is unavailable, outside the associate's scope, or is not a therapy program:

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

The existing `PATCH <baseURL>/programs/therapy-programs/<program_id>/` accepts `price`, `is_credit`, and
`is_complimentary` under its merged-state validation rules. Omitted flags retain their stored values.
`credit_received` remains read-only on this PATCH; supplied amounts are ignored and removed from validated program
data before validation or saving. Credit amounts are not required or validated during updates. Use the receipt POST to add newly
received amounts and optionally change the flags. Assigned therapy-service PATCH also accepts top-level flags for
its standalone or composite parent program without creating a receipt.
Program creation remains unchanged and still accepts its existing flag and initial credit-amount inputs.
Payment history contains only receipts recorded through the new POST.

The payment-history model and its new nullable `notes` field require database migrations generated and applied by the
project owner before these APIs are used. Existing payment records return `notes: null` after the field is added.
Moving the existing flags to the payments request requires no additional model change or migration.
