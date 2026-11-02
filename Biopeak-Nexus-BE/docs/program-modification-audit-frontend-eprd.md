# Program History — Frontend ePRD

Show staff the fields changed on an assigned program, their previous and current values, who changed them, and when.

Use `Authorization: Bearer <token>`. Admins may read any program's history without a center header. Associates must send a valid `X-Center-ID` context and have an active assignment at an active owning or redeemable center of the program. Customers cannot access this endpoint. Cancelled and expired programs remain accessible to authorized staff.

## Logical Flow

1. **Load program history** — Fetch the selected program's history when opened, paginate the results, and refetch after a successful program modification to show the latest entries.

## API Requests

### 1. Load program history

Retrieve a paginated list of field changes for one assigned program, ordered newest first.

**Method:** `GET`

**URL:** `<baseURL>/programs/<pk>/history/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `pk` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Parent Program UUID from the program list/detail; do not use a template, catalogue service, or assigned program-service ID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Requested page; defaults to 1. |
| `limit` | No | `10` | Page size; defaults to 10, maximum 50. |

Only pagination is implemented. There are no search, field, actor, date, active-status, or client-selected ordering filters.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019fb7eb-25aa-7261-9f30-a41766a24bc1",
      "changed_field": "Credit amount",
      "changed_field_code": "credit_received",
      "previous_value": "3000.00",
      "current_value": "5000.00",
      "created_by": {
        "id": "0199e800-0000-7000-8000-000000000008",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-21T10:00:00+05:30"
      },
      "created_at": "2026-10-21T10:05:00+05:30"
    }
  ]
}
```

#### Logic

- Render one row per returned item: timestamp, creator, `changed_field`, `previous_value`, and `current_value`. Use `id` as the row identifier and `changed_field_code` for field-specific formatting. `created_by` may be null; its `image` and `last_login` may also be null.
- Both values are nullable strings. Preserve the distinction between null and empty text. Amounts are decimal strings; dates/timestamps are ISO strings; boolean values are the strings `"true"` and `"false"`.
- `center` and `cancelled_by` values contain UUID strings. `redeemable_centers` contains a sorted UUID array encoded as text, for example `"[\"019ed45d-d6c4-7534-830e-501019fd98dd\"]"`. Names are not snapshotted for these values; parse center arrays only when formatting that field.
- Tracked field codes are `center`, `notes`, `expires_at`, `is_complimentary`, `is_credit`, `price`, `credit_received`, `created_date`, `redeemable_centers`, `is_active`, `cancellation_reason`, `cancelled_by`, `cancelled_at`, and `cancelled_date`.
- `count` counts changed fields, not modification requests. A request changing price and expiry produces two rows. The API has no request-group identifier; do not infer request grouping from matching actors or timestamps. Timestamp ties use UUID descending.
- Use `next` and `previous` to navigate pages. A program without recorded history returns `count: 0`, `next: null`, `previous: null`, and `data: []`; show an empty-history state. An empty history does not mean the program was never modified.
- Recording currently covers therapy/composite Program edits, program-center additions, and cancellations, including parent Program changes made during service cancellation. The therapy payments POST records changes to `is_credit` and `is_complimentary` in the receipt transaction. Assigned therapy-service PATCH also records parent flag changes with the authenticated staff user in the same transaction as any session increments. Refresh this history after either operation changes a flag. The receipt total increment itself is not audited. Initial creation, unchanged values, service/session-only changes, derived counters, and automatic timestamps produce no rows. Failed operations produce no committed history. Older edits, direct database updates, and maintenance commands are not reconstructed.

History is read-only; this frontend flow has no create, edit, or delete operation. The user-owned migration for `ProgramAuditLog` must be applied before this endpoint is used.

#### Errors

`404 Not Found` — the program does not exist or is outside the associate's accessible centers:

```json
{
  "detail": "Program not found."
}
```

Treat this as an unavailable program, separate from the successful empty-history state. Customers and associates without valid center context are denied by the existing permission checks.
