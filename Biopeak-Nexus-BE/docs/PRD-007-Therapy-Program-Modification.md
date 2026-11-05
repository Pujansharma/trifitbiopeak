# Therapy Program Modification ePRD

Modify an existing standalone therapy program, add service sessions and redemption locations, and retrieve complete selections beyond the previews.

Authorization: Bearer <token>. Associates continue to send their valid X-Center-ID request context. Admins may modify any program; associates need an active assignment at its existing owning center or an existing program redeemable center. Customers cannot modify programs; they may read their own program data.

## Logical Flow

1. **List available program redeemable centers** — Discover the customer profile's linked centers and identify existing selections and the home center before adding redemption locations.
2. **List available therapy services** — Discover global therapy services and services assigned to the program's redeemable centers, including existing selections.
3. **Modify therapy program** — PATCH the already loaded program with changed metadata and additions. The response contains the same detail shape as GET, but its services preview may be stale. After success, GET the same URL for current service data.
4. **List program redeemable centers** — Retrieve the complete paginated selections when the five-center program preview is insufficient.
5. **List assigned therapy services** — Retrieve service lines beyond the five-service preview and their assigned program-service IDs.
6. **Retrieve assigned therapy service** — Retrieve all selected centers for one service line when its five-center preview is insufficient.

## API Requests

### 1. List available program redeemable centers

List centers linked to the program's customer profile, including centers already selected for program redemption.

**Method:** `GET`

**URL:** `<baseURL>/programs/therapy-programs/<program_id>/available-redeemable-centers/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Standalone therapy program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Bengaluru` | Trimmed, case-insensitive name substring or code prefix. Blank applies no search filter. |
| `active` | No | `1` | `1` selects active centers; `0` selects inactive centers. Omitted or invalid values include both. Assignment active status is not filtered. |
| `page` | No | `1` | Defaults to 1. |
| `limit` | No | `10` | Defaults to 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru",
      "exists": false,
      "is_home_center": true
    }
  ]
}
```

#### Logic

Admins and associates may read; customers may read only programs belonging to their own customer account. The profile is resolved from the program, not a separately supplied profile ID. All profile-linked centers and assignments are included by default, including inactive records. Centers outside that profile's assignments are excluded even if already selected on the program.

`exists` checks membership in program.redeemable_centers. `is_home_center` checks the profile's is_primary assignment independently, so a home center can have exists=false. If no primary assignment exists, every row has is_home_center=false. These flags do not depend on expiry, remaining sessions, catalogue availability, or program active status.

Order is home center first, then exists=true, then center created_at descending and UUID descending. No matching centers returns count=0 and data=[]. Send intended additions through operation 3 and refresh this list after success; this GET does not modify assignments. Availability discovery and write validation remain separate: inactive or otherwise invalid additions may still be rejected by the existing PATCH rules.

#### Errors

`404 Not Found` — missing program or a program outside customer ownership:

```json
{
  "detail": "Therapy program not found."
}
```

### 2. List available therapy services

List catalogue therapy services for selection with the same readable fields as GET /services/, plus exists.

**Method:** `GET`

**URL:** `<baseURL>/programs/therapy-programs/<program_id>/available-services/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Standalone therapy program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Recovery` | Trimmed, case-insensitive name substring. Blank applies no search filter. |
| `active` | No | `1` | `1` selects active services; `0` selects inactive services. Omitted or invalid values include both. |
| `exists` | No | `0` | `1` selects services already in this program; `0` selects services not in this program. Omitted or invalid values include both. |
| `page` | No | `1` | Defaults to 1. |
| `limit` | No | `10` | Defaults to 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "name": "Recovery Therapy",
      "is_global": false,
      "centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
          "code": "C0001",
          "name": "Biopeak Bengaluru"
        }
      ],
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "centers_count": 2,
      "care_template": {
        "pre_template_name": "recovery_pre_care",
        "post_template_name": "recovery_post_care"
      },
      "created_at": "2026-10-20T16:00:00+05:30",
      "updated_at": "2026-10-20T16:00:00+05:30",
      "is_active": true,
      "is_locked": true,
      "created_by": "019ed45e-a122-7a01-b063-b7c03281893f",
      "exists": false
    }
  ]
}
```

#### Logic

Admins and any associates may read; customers cannot access this endpoint. Service category is fixed to therapy.
Center scope comes only from program.redeemable_centers. There is no center_id, category, or service_type query filter,
and X-Center-ID does not change this list's center scope.

Candidates are global services (is_global=true) or services assigned to any program redeemable center. With no
redeemable centers, only global therapy services are returned. Matching multiple centers does not duplicate a service.
Search, active, and exists filters apply to global services too. Results are ordered by catalogue service created_at descending.

exists is true when a ProgramService links this catalogue service to this program, including retained inactive or
cancelled assignments. is_locked keeps the catalogue meaning: the service is assigned to any program. A service
assigned only elsewhere can therefore have is_locked=true and exists=false. The response id is the catalogue service
UUID for add_services[].id; it is not an assigned ProgramService UUID.

Use `?exists=0` to discover services not yet in the program, or `?exists=1` to list existing selections within the
available catalogue scope. The filter uses the same membership subquery as the response flag and combines with
search and active filters before pagination.

centers preserves the catalogue preview of up to five active centers, restricted to this program's redeemable centers.
The stored centers_count remains the catalogue-wide total, so it can exceed the preview length. Global services
normally have an empty centers array. care_template and created_by may be null; created_by is a user UUID when present.
The catalogue's write-only add_centers and remove_centers fields do not appear in this GET response.

No matching services returns count=0 and data=[]. Use operation 3 for intended additions and refresh this list after
success. This discovery GET does not modify assignments or change the existing addition-validation rules.

#### Errors

`404 Not Found` — missing or non-therapy program:

```json
{
  "detail": "Therapy program not found."
}
```

### 3. Modify therapy program

Update metadata and append services, sessions, or selected redemption centers atomically.

**Method:** PATCH

**URL:** <baseURL>/programs/therapy-programs/<program_id>/

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Standalone therapy program UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `center_id` | No | `019ed45d-d6c4-7534-830e-501019fd98dd` | Owning center; must be active. Changing it requires the existing creation authorization. Grants no redemption access. |
| `created_date` | No | `2026-10-20` | Program creation date, YYYY-MM-DD. |
| `expires_at` | Conditional | `2026-12-20` | On or after today. Null is accepted for an unexpired program; an expired program must send a non-null renewal date. |
| `is_complimentary` | No on PATCH | `false` | Boolean; omission retains its stored value. Cannot be true with the resulting is_credit=true. |
| `is_credit` | No on PATCH | `true` | Boolean; omission retains its stored value. Credit programs require a price; credit_received is not required or validated during update. |
| `price` | Conditional | `12000.00` | Required in the resulting state when is_complimentary=false, including credit programs; an existing price may be retained. Otherwise nullable. |
| `notes` | No | `Two additional sessions` | String, blank, or null. Omission retains the stored value. |
| `add_redeemable_centers` | No | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Append program centers. Each must already be linked to the program customer profile. Empty adds nothing. |
| `add_redeemable_centers[].id` | Yes per entry | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID. |
| `add_services` | No | `[{"id":"019e1622-403b-74d1-a991-df3b388b4ac8","sessions_count":2,"centers":["019ed45d-d6c4-7534-830e-501019fd98dd"]}]` | Append services, sessions, or center selections. Duplicate service IDs are rejected. |
| `add_services[].id` | Yes per entry | `019e1622-403b-74d1-a991-df3b388b4ac8` | Catalog therapy service UUID. An existing matching line must be active and unambiguous. |
| `add_services[].sessions_count` | Conditional | `2` | Positive increment for an existing line; required initial allowance for a new line. Omit for centers-only changes. |
| `add_services[].centers` | Conditional | `["019ed45d-d6c4-7534-830e-501019fd98dd"]` | UUID array. Required and nonempty for a new line; optional or empty for an existing line. Append only. |

```json
{
  "expires_at": "2026-12-20",
  "price": "12000.00",
  "notes": "Two additional sessions",
  "add_redeemable_centers": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
    }
  ],
  "add_services": [
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "sessions_count": 2,
      "centers": [
        "019ed45d-d6c4-7534-830e-501019fd98dd"
      ]
    }
  ]
}
```

Only send changed metadata and intended additions. Existing allowance 4 plus sessions_count 2 becomes 6; sessions_used remains 1. Repeating the request adds another 2. There is no idempotency-key support. To add only centers, omit sessions_count. Omitted services and centers remain assigned. Only declared serializer fields are processed.

To add sessions directly to one assigned therapy service, use the detail PATCH with the sessions_count increment described in [Add therapy sessions](PRD-009-Program-Service-Responsibilities.md#2-add-therapy-sessions). That operation allows admins and any associates, requires active and unexpired program/service state, and does not renew the program.

Service center IDs must belong to the union of stored program centers and add_redeemable_centers in this request, and the service must currently be available at each supplied center. Adding a program center does not expand existing service selections. The owning center requires explicit selections at both levels.

| Program type | is_complimentary | is_credit | Price |
| --- | --- | --- | --- |
| Complimentary | true | false | Optional/null |
| Credit | false | true | Required |
| Regular paid | false | false | Required |
| Invalid | true | true | Rejected |

Flags and price are writable on PATCH and validated against the merged state. Omitted flags retain their stored values; explicit false is applied. When switching from complimentary to credit or regular paid, supply a price in this PATCH if none is stored. No credit amount is required or validated during update, including when the stored total is null. Flags may also be updated through [Program Payments](PRD-010-Program-Payments.md) or assigned therapy-service PATCH. Cancelled programs and cancelled service lines reject modification. Expired programs require renewal in this request. Invalid additions roll back metadata changes too.

`credit_received` is accepted as an initial amount during creation and is read-only on PATCH. Supplied update values are ignored and removed from validated program data before metadata validation or saving. No credit-amount validation runs on update. Use the payments POST to add receipt amounts to the stored total; changing flags does not reset it, and totals may exceed `price`. All therapy program responses, including nested program representations, return `credit_received` as a decimal string or null.

Each changed Program field creates one audit row in the same transaction; unchanged values, service/session-only additions, and automatic counters do not. Program redeemable-center changes are recorded as a field change. Failed requests create neither modifications nor audit entries. Staff can retrieve history using [Program Modification Audit API](program-modification-audit-frontend-eprd.md).

Zero assigned sessions provide no redemption allowance. Positive additions to an existing zero-session line increase its allowance normally.

#### Response — 200 OK

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "019fb7e8-ffde-716e-9ebc-4dbd2bb180fb",
    "uid": "P0001",
    "profile": {
      "id": "019ed45e-91bc-7c85-9e28-13720320d10c",
      "contact_email": "customer@example.com",
      "phone": "+919876543210",
      "first_name": "Rohan",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-05-12",
      "image": null,
      "home_center": {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      },
      "created_at": "2026-10-20T16:00:00+05:30",
      "updated_at": "2026-10-20T16:00:00+05:30"
    },
    "program_type": "therapy",
    "is_complimentary": false,
    "is_credit": true,
    "price": "12000.00",
    "credit_received": "5000.00",
    "notes": "Two additional sessions",
    "expires_at": "2026-12-20",
    "sessions_count": 6,
    "sessions_used": 1,
    "sessions_cancelled": 0,
    "services_count": 1,
    "redeemable_centers": [
      {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "created_by": {
      "id": "019ed451-f21b-7be9-8d05-86a985ce31c7",
      "email": "staff@example.com",
      "first_name": "Ananya",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-20T16:00:00+05:30"
    },
    "created_at": "2026-10-20T16:00:00+05:30",
    "updated_at": "2026-10-20T16:00:00+05:30",
    "is_active": true,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "created_date": "2026-10-20",
    "cancelled_date": null,
    "services": [
      {
        "id": "019fb7e9-12aa-7261-9f30-a41766a24bc1",
        "program": {"id":"019fb7e8-ffde-716e-9ebc-4dbd2bb180fb","uid":"P0001","profile":{"id":"019ed45e-91bc-7c85-9e28-13720320d10c","contact_email":"customer@example.com","phone":"+919876543210","first_name":"Rohan","last_name":"Shah","gender":"Male","date_of_birth":"1990-05-12","image":null,"is_main":true,"is_legacy":false,"is_onboarding_sent":true,"is_onboarding_completed":true,"is_converted":true,"created_at":"2026-10-20T16:00:00+05:30","updated_at":"2026-10-20T16:00:00+05:30"},"program_type":"Therapy Program","notes":"Two additional sessions","expires_at":"2026-12-20","is_complimentary":false,"is_credit":true,"price":"12000.00","credit_received":"5000.00","services_count":1,"sessions_count":6,"sessions_used":1,"sessions_cancelled":0,"redeemable_centers_count":1,"cancellation_reason":null,"cancelled_by":null,"cancelled_at":null,"created_date":"2026-10-20","cancelled_date":null,"is_active":true,"created_at":"2026-10-20T16:00:00+05:30","updated_at":"2026-10-20T16:00:00+05:30"},
        "service": {"id":"019e1622-403b-74d1-a991-df3b388b4ac8","name":"Recovery Therapy","service_category":"Therapy","service_category_code":"therapy","image":null,"centers":[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd","code":"C0001","name":"Biopeak Bengaluru"}]},
        "sessions_count": 6,
        "sessions_used": 1,
        "sessions_cancelled": 0,
        "redeem_code": "AB12345678",
        "created_date": "2026-10-20",
        "created_at": "2026-10-20T16:00:00+05:30",
        "is_active": true,
        "can_redeem": true,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "active_appointment": null
      }
    ]
  }
}
```

The response previews at most five services, five program centers, and five service centers, preserving each collection's existing ordering. Counts refer to the complete collections. The PATCH response reuses the services preview loaded before the update; it is not queried again after saving. That preview can therefore contain stale service lines, counters, center selections, nested program data, and can_redeem values, and may omit newly added services. Clients must GET `<baseURL>/programs/therapy-programs/<program_id>/` after a successful PATCH to obtain current service data.

On GET, service.centers contains this program-service line's stored selections, including selections that later become unavailable. can_redeem reflects the requested X-Center-ID when provided; otherwise it checks whether any selected center can currently redeem. active_appointment is null here because no open appointment exists; a populated value follows the existing appointment contract.

#### Errors

400 Bad Request — unavailable supplied center:

```json
{
  "detail": {
    "add_services": [
      {
        "centers": "This service is not available at every selected center."
      }
    ]
  }
}
```

400 Bad Request — cancelled program:

```json
{
  "detail": "Cancelled programs cannot be updated."
}
```

403 Forbidden — associate lacks an assignment at an existing program center:

```json
{
  "detail": "You are not assigned to a center of this program."
}
```

### 4. List program redeemable centers

Retrieve all explicitly selected program centers, including ones missing from the preview.

**Method:** GET

**URL:** <baseURL>/programs/therapy-programs/<program_id>/redeemable-centers/

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Standalone therapy program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Defaults to 1. |
| `limit` | No | `10` | Defaults to 10; maximum 50. |

#### Response — 200 OK

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    }
  ]
}
```

### 5. List assigned therapy services

Retrieve the program's service lines; use service.id for add_services[].id and the outer id for individual service detail.

**Method:** GET

**URL:** <baseURL>/programs/therapy-programs/<program_id>/services/

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `019fb7e8-ffde-716e-9ebc-4dbd2bb180fb` | Standalone therapy program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Defaults to 1. |
| `limit` | No | `10` | Defaults to 10; maximum 50. |

#### Response — 200 OK

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019fb7e9-12aa-7261-9f30-a41766a24bc1",
      "program": {
        "id": "019fb7e8-ffde-716e-9ebc-4dbd2bb180fb",
        "uid": "P0001",
        "profile": {"id":"019ed45e-91bc-7c85-9e28-13720320d10c","contact_email":"customer@example.com","phone":"+919876543210","first_name":"Rohan","last_name":"Shah","gender":"Male","date_of_birth":"1990-05-12","image":null,"is_main":true,"is_legacy":false,"is_onboarding_sent":true,"is_onboarding_completed":true,"is_converted":true,"created_at":"2026-10-20T16:00:00+05:30","updated_at":"2026-10-20T16:00:00+05:30"},
        "program_type": "Therapy Program",
        "notes": "Two additional sessions",
        "expires_at": "2026-12-20",
        "is_complimentary": false,
        "is_credit": true,
        "price": "12000.00",
        "credit_received": "5000.00",
        "services_count": 1,
        "sessions_count": 6,
        "sessions_used": 1,
        "sessions_cancelled": 0,
        "redeemable_centers_count": 1,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "created_date": "2026-10-20",
        "cancelled_date": null,
        "is_active": true,
        "created_at": "2026-10-20T16:00:00+05:30",
        "updated_at": "2026-10-20T16:00:00+05:30"
      },
      "service": {
        "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
        "name": "Recovery Therapy",
        "service_category": "Therapy",
        "service_category_code": "therapy",
        "image": null,
        "centers": [{"id":"019ed45d-d6c4-7534-830e-501019fd98dd","code":"C0001","name":"Biopeak Bengaluru"}]
      },
      "sessions_count": 6,
      "sessions_used": 1,
      "sessions_cancelled": 0,
      "redeem_code": "AB12345678",
      "created_date": "2026-10-20",
      "created_at": "2026-10-20T16:00:00+05:30",
      "is_active": true,
      "can_redeem": true,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "active_appointment": null
    }
  ]
}
```

The centers array in each service remains a preview of up to five stored selections. No center removal or service deletion operation exists in this modification flow.

### 6. Retrieve assigned therapy service

Retrieve the service line with its complete selected-center array.

**Method:** GET

**URL:** <baseURL>/programs/program-services/therapy-services/<program_service_id>/

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `019fb7e9-12aa-7261-9f30-a41766a24bc1` | Assigned program-service UUID; not the catalog service UUID. |

#### Response — 200 OK

```json
{
  "detail": "Details.",
  "data": {
    "id": "019fb7e9-12aa-7261-9f30-a41766a24bc1",
    "program": {
      "id": "019fb7e8-ffde-716e-9ebc-4dbd2bb180fb",
      "uid": "P0001",
      "profile": {
        "id": "019ed45e-91bc-7c85-9e28-13720320d10c",
        "contact_email": "customer@example.com",
        "phone": "+919876543210",
        "first_name": "Rohan",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-05-12",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": true,
        "is_onboarding_completed": true,
        "is_converted": true,
        "created_at": "2026-10-20T16:00:00+05:30",
        "updated_at": "2026-10-20T16:00:00+05:30"
      },
      "program_type": "Therapy Program",
      "notes": "Two additional sessions",
      "expires_at": "2026-12-20",
      "is_complimentary": false,
      "is_credit": true,
      "price": "12000.00",
      "credit_received": "5000.00",
      "services_count": 1,
      "sessions_count": 6,
      "sessions_used": 1,
      "sessions_cancelled": 0,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "created_date": "2026-10-20",
      "cancelled_date": null,
      "is_active": true,
      "created_at": "2026-10-20T16:00:00+05:30",
      "updated_at": "2026-10-20T16:00:00+05:30"
    },
    "service": {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "name": "Recovery Therapy",
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "centers": [
        {"id":"019ed45d-d6c4-7534-830e-501019fd98dd","code":"C0001","name":"Biopeak Bengaluru"}
      ]
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "sessions_count": 6,
    "sessions_used": 1,
    "sessions_cancelled": 0,
    "redeem_code": "AB12345678",
    "created_date": "2026-10-20",
    "created_by": {
      "id": "019ed451-f21b-7be9-8d05-86a985ce31c7",
      "email": "staff@example.com",
      "first_name": "Ananya",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-20T16:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-20T16:00:00+05:30",
    "updated_at": "2026-10-20T16:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

Selected centers remain visible when catalog availability is removed. Slots, booking, rescheduling, QR redemption, and appointment completion revalidate service selections and live availability. Program-level redeem-all rejects the whole request if any remaining active service cannot be redeemed at the requested center.
