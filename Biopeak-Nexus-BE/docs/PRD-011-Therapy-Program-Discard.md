# Therapy Program Discard — Frontend ePRD

Authenticated endpoints use Bearer tokens.

## Logical Flow

1. **Discard a therapy program** — Permanently discard the program and all its assigned therapy services.
2. **Discard a therapy service** — Permanently discard one assignment while retaining its parent program.

Only admins and associates may call these actions. Both require a valid center
UUID in `X-Center-ID`. Associates require an active assignment at that center;
admins do not require a center assignment. Customers cannot discard records.

The owning program's center must match `X-Center-ID`. A program or service
owned by another center returns the corresponding not-found response.

Program and service detail, list, and preview responses expose read-only
`is_discarded`, initially `false`. Use this flag to identify discarded records;
discard does not change `is_active` or cancellation metadata. Neither action
accepts editable fields: send `{}`. Detail PATCH cannot change `is_discarded`,
and there is no restore action. Repeated discard returns the same success.

Read-only `discarded_by` identifies the staff user who first discarded the
program or service, using the existing nested user object. Both actions save
the authenticated request user; clients cannot choose or overwrite this value.
Program discard stamps the same user on newly discarded child services and
preserves attribution on previously discarded children. Repeated requests keep
the original user. The field is `null` before discard, for historical discards
without attribution, or after the recorded user is deleted.

Cancelled, expired, partially-used, and fully-used records can be discarded.
Existing appointments, redemption history, and individual service session
counters remain unchanged. Discarded records remain readable but cannot be
booked, redeemed, completed through a linked appointment, extended, or cancelled.
Linked rescheduling and slot eligibility reject discarded entitlements.

Parent `sessions_count`, `sessions_used`, `sessions_cancelled`, `services_count`,
and `services_cancelled` exclude discarded assignments. Ordinary cancelled
assignments remain included. Three one-session assignments with one cancelled
therefore have three total sessions and one cancelled session; discarding that
cancelled assignment changes those totals to two and zero.

After success, refresh the existing program detail, service list, and any
affected previews: the action response contains the discard flag and staff
attribution rather than refreshed counters.

Assigned-service lists accept the optional query parameter `discarded` on both
`<baseURL>/programs/therapy-programs/<pk>/services/` and
`<baseURL>/profiles/<pk>/programs/therapy-programs/<program_pk>/services/`.

| Query | Returned assignments |
| --- | --- |
| `discarded=0` | `is_discarded: false` only. |
| `discarded=1` | `is_discarded: true` only. |
| Omitted | Both discarded and non-discarded assignments. |

Other values are ignored. Filtering affects the returned list and pagination
count, independently of cancellation status; parent totals still exclude
discarded assignments regardless of the selected filter.

The center therapy-program list at
`<baseURL>/centers/<pk>/therapy-programs/` and the customer therapy-program list
at `<baseURL>/profiles/<pk>/programs/therapy-programs/` accept `discarded=0|1`,
filtering the program's own `is_discarded` flag. Both default to `discarded=0`
when omitted: `0` returns non-discarded programs, and `1` returns discarded
programs. Other values are ignored, retaining the non-discarded default.
The filter combines with existing list filters.

Customer therapy summaries at
`<baseURL>/profiles/<pk>/programs/therapy-programs/summary/` exclude discarded
programs from total, inactive, expired, and completed program counts and from
session totals. Session totals use the stored program counters, which already
exclude discarded service assignments. The customer view computes its own
summary independently of the deprecated external views.

The overall customer summary at
`<baseURL>/profiles/<pk>/programs/summary/` also excludes discarded therapy
programs from aggregate counts and `programs_by_type`. Its service statistics
exclude discarded assignments and assignments under discarded therapy programs.
Non-discarded cancelled programs and assignments remain counted under the
existing status rules. These exclusions do not depend on list query parameters.

## 1. Discard a therapy program

POST (Authenticated): `<baseURL>/programs/therapy-programs/<pk>/discard/`

### Params

| Name | In | Required | Description |
| --- | --- | --- | --- |
| `pk` | path | Yes | Therapy program UUID; also its parent Program UUID. |

All assigned therapy services are discarded, including previously cancelled
assignments; all five parent totals become zero. Redeemable-center counts stay
unchanged, and no cancellation history is added.

### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "is_discarded": true,
    "discarded_by": {
      "id": "019b6927-81eb-74c2-bed5-82604bc4d110",
      "email": "staff@example.com",
      "first_name": "Aarav",
      "last_name": "Shah",
      "image": null,
      "last_login": null
    }
  }
}
```

### Error — `404 Not Found`: program unavailable

```json
{
  "detail": "Therapy program not found with this ID"
}
```

### Error — `404 Not Found`: missing or unknown center

```json
{
  "detail": "Invalid center ID provided"
}
```

## 2. Discard a therapy service

POST (Authenticated): `<baseURL>/programs/program-services/therapy-services/<pk>/discard/`

### Params

| Name | In | Required | Description |
| --- | --- | --- | --- |
| `pk` | path | Yes | Assigned ProgramService UUID, not catalogue Service UUID. |

Only assignments owned by therapy programs are supported. Discarding the last
assignment does not discard or cancel the parent program.

### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "is_discarded": true,
    "discarded_by": {
      "id": "019b6927-81eb-74c2-bed5-82604bc4d110",
      "email": "staff@example.com",
      "first_name": "Aarav",
      "last_name": "Shah",
      "image": null,
      "last_login": null
    }
  }
}
```

### Error — `400 Bad Request`: center header omitted

```json
{
  "detail": "X-Center-ID header is required."
}
```

### Error — `404 Not Found`: unknown center

```json
{
  "detail": "Center not found with this ID."
}
```

### Error — `404 Not Found`: assignment unavailable or composite-owned

```json
{
  "detail": "Therapy program service not found."
}
```
