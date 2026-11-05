# Customer Composite Programs — Frontend PRD

## 1. Summary

Build the customer-profile composite-program experience for administrators and
authorized associates. The frontend can list programs for a customer profile,
assign a composite template as a new program, and edit a limited set of
program-level fields.

The program operations are:

| Method | Purpose | Endpoint |
|---|---|---|
| `GET` | List a customer's composite programs | `/profiles/:profile_id/programs/composite-programs/` |
| `POST` | Assign a composite template to the customer | `/profiles/:profile_id/programs/composite-programs/` |
| `PATCH` | Edit allowed program fields | `/programs/composites/programs/:composite_program_id/` |

Services are assigned from the selected composite template during creation.
Membership and session counts are read-only. During assignment, optionally select
centers per therapy service; services cannot be added, removed, or modified through PATCH.

Post-creation assessment and therapy add-ons and the profile-scoped assigned
service list are documented separately in
[Composite Program Add-Ons — Frontend ePRD](composite-program-add-ons-frontend-eprd.md).

## 2. Access and Headers

All requests require:

```http
Authorization: Bearer <access_token>
X-Center-ID: <center_uuid>
Content-Type: application/json
```

- Administrators can access a customer profile assigned to the selected center.
- Associates must be actively assigned to the selected center and actively
  linked to the customer profile at that center.
- Customers cannot use these endpoints.
- The `X-Center-ID` value becomes the owning center for a program created by POST.

## 3. Data Semantics

For templates containing therapy, `therapy_redemption_is_global` is optional and writable during assignment. Explicit false requires nonempty parent `redeemable_centers`; omitting both fields defaults to true. With the flag omitted, empty centers also default to true and nonempty centers select scoped coverage. Explicit true ignores supplied parent centers and stores no parent selections. Scoped coverage requires active customer centers. Templates without therapy retain their nonempty-center requirement.

Therapy service selections reuse `TherapyProgramService.redeemable_centers`. Optionally submit them as `therapy_services: [{"id":"<catalogue_service_id>","centers":[{"id":"<center_id>"}]}]`. The previous `therapy_service_centers` request field is removed. The list may be omitted, empty, or partial, and each nested `centers` list may be omitted or empty. All active template therapies are still created with fixed sessions. Missing selections store empty centers without inheriting parent centers. Supplied entries require a unique active template therapy ID; null lists remain invalid. Each explicitly selected service center must belong to the scoped program centers and actively offer that service. Program centers must be active and actively assigned to the customer.

For scoped composites, a therapy with empty centers automatically returns `can_redeem: false` and backend redemption is blocked until centers are assigned. Adding centers does not bypass expiry, session, activity, or live availability checks. The existing shared eligibility query supplies this behavior; no persisted redemption flag is added.

Empty or omitted service selections under a global composite retain dynamic redemption at active customer centers currently offering the therapy. Explicit global service selections narrow coverage and must pass the same customer-membership and live service-availability checks. Template `quantity` supplies the fixed therapy session count; assignment never accepts session overrides.

Both creation routes accept optional `expires_at` as `YYYY-MM-DD` or null. Omission/null means no expiry; today or later is valid. This date applies to the whole composite, with existing redemption and booking expiry checks retained.

Both creation routes accept `is_credit` (default false), `is_complimentary` (default true), `price`, and initial `credit_received`. Both flags cannot be true. Non-complimentary programs require price; credit programs additionally require a non-null credit amount. Credit amounts allow zero, reject negatives, and support 10 total digits with 2 decimal places without a cap tied to price. Creation stores the amount without creating a payment receipt. Creation/list/detail responses expose `is_credit` and `credit_received` (decimal string or null); the new credit fields are read-only on composite PATCH.

Assigned composite therapy center arrays are prefetched previews of at most five selections. Use the existing paginated `/programs/program-services/therapy-services/<service_id>/redeemable-centers/` for all selections and `available-redeemable-centers/` for the center picker. The existing center PATCH accepts `add_centers: [{"id":"<center_uuid>"}]`. Standalone therapy redemption rules are unchanged; assigned therapy detail also limits center previews to five.

Parent composite PATCH accepts `therapy_redemption_is_global` and `redeemable_centers`. Switching off requires nonempty supplied or existing centers; switching on ignores supplied parent centers and clears parent selections. A scoped parent cannot exclude existing service selections. Reload the composite after editing coverage.

Top-level `description` is the editable program description stored on
`composite_program.program.description`. The nested `composite_template`
reference exposes only `id`, `code`, `name`, and `is_active`.

The `services` field is a preview of assigned services. `services_count` is the
authoritative total. The service-category counters include both template
services and add-ons. `add_ons_count` is an overlapping subset and must not be
added to the category counters or to `services_count`. All counters include
inactive and cancelled assigned services. The frontend must treat every count,
service, and service-session field as read-only.

## 4. GET — List Customer Composite Programs

### Endpoint

```http
GET /profiles/:profile_id/programs/composite-programs/
```

### Query parameters

| Parameter | Values | Behavior |
|---|---|---|
| `active` | `0`, `1` | Filters inactive or active programs |
| `expired` | `0`, `1` | Filters expired or unexpired programs |
| `search` | string | Case-insensitive template code/name or program UID search |
| `page` | positive integer | Requested results page |
| `limit` | `1`–`50` | Page size |

The endpoint returns all composite programs belonging to the authorized
customer profile. Service `can_redeem` values are evaluated against the center
in `X-Center-ID`.

### Request payload

```json
null
```

### Success response

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<composite_program_uuid>",
      "profile": {
        "id": "<customer_profile_uuid>",
        "contact_email": "<email|null>",
        "phone": "<phone>",
        "first_name": "<string>",
        "last_name": "<string>",
        "gender": "<string|null>",
        "date_of_birth": "<date|null>",
        "image": "<url|null>",
        "home_center": {
          "id": "<center_uuid>",
          "code": "<string>",
          "name": "<string>"
        },
        "created_at": "<datetime>",
        "updated_at": "<datetime>"
      },
      "center": {
        "id": "<center_uuid>",
        "code": "<string>",
        "name": "<string>"
      },
      "composite_template": {
        "id": "<composite_template_uuid>",
        "code": "<template_sku>",
        "name": "<string>",
        "is_active": true
      },
      "name": "<string|null>",
      "assessment_type": "<Baseline|null>",
      "assessment_type_code": "<baseline|null>",
      "program_type": "composite",
      "notes": "<string|null>",
      "description": "<program_description|null>",
      "expires_at": "<date|null>",
      "is_complimentary": true,
      "is_credit": false,
      "credit_received": null,
      "price": "<decimal_string|null>",
      "redeemable_centers": [
        {
          "id": "<center_uuid>",
          "code": "<string>",
          "name": "<string>"
        }
      ],
      "redeemable_centers_count": 1,
      "services": [
        {
          "id": "<program_service_uuid>",
          "service": {
            "id": "<service_uuid>",
            "name": "<string>",
            "service_category": "<string>",
            "service_category_code": "<therapy|assessment|consultation>",
            "image": "<url|null>"
          },
          "service_assignment_type": "<string>",
          "service_assignment_type_code": "<standalone|add_on>",
          "sessions_count": "<integer|null>",
          "sessions_used": "<integer|null>",
          "sessions_cancelled": "<integer|null>",
          "redeem_code": "<string|null>",
          "can_redeem": true,
          "cancellation_reason": "<string|null>",
          "cancelled_by": "<user_object|null>",
          "cancelled_at": "<datetime|null>",
          "cancelled_date": "<date|null>",
          "created_date": "<date>",
          "created_by": "<user_object|null>",
          "is_active": true,
          "created_at": "<datetime>",
          "updated_at": "<datetime>"
        }
      ],
      "services_count": 1,
      "add_ons_count": 0,
      "assessment_services_count": 1,
      "therapy_services_count": 0,
      "consultation_services_count": 0,
      "cancellation_reason": "<string|null>",
      "cancelled_by": "<user_object|null>",
      "cancelled_at": "<datetime|null>",
      "cancelled_date": "<date|null>",
      "created_date": "<date>",
      "is_active": true,
      "created_at": "<datetime>",
      "updated_at": "<datetime>",
      "created_by": "<user_object|null>"
    }
  ]
}
```

## 5. POST — Create Customer Composite Program

### Endpoint

```http
POST /profiles/:profile_id/programs/composite-programs/
```

The customer profile is derived from `:profile_id`. Do not include a profile ID
or center ID in the request body. The owning center is derived from
`X-Center-ID`.

### Request payload structure

For a scoped template containing assessment and therapy services, including initial credit:

```json
{
  "composite_template_id": "<composite_template_uuid>",
  "name": "<composite_program_name|null>",
  "assessment_type": "baseline",
  "notes": "<string|null>",
  "expires_at": "2027-01-30",
  "is_complimentary": false,
  "is_credit": true,
  "price": "12000.00",
  "credit_received": "3000.00",
  "redeemable_centers": [
    {
      "id": "<center_uuid>"
    }
  ],
  "therapy_services": [
    {
      "id": "<catalogue_therapy_service_uuid>",
      "centers": [{"id": "<center_uuid>"}]
    }
  ],
  "created_date": "2026-10-30"
}
```

For a global therapy template without assessment services, omit assessment-only
fields. Empty service restrictions and no expiry are allowed:

```json
{
  "composite_template_id": "<composite_template_uuid>",
  "notes": "<string|null>",
  "expires_at": null,
  "is_complimentary": true,
  "is_credit": false,
  "credit_received": null,
  "price": null,
  "therapy_redemption_is_global": true,
  "redeemable_centers": [],
  "therapy_services": [],
  "created_date": "<date>"
}
```

### Field rules

| Field | Required | Rules |
|---|---|---|
| `composite_template_id` | Yes | Must identify an active template with active services |
| `name` | No | Currently used only for assessment-service programs; accepts a string, `""`, or `null`; `""` is stored as `null` |
| `assessment_type` | Conditional | Accepts `baseline` or `null`; required when the template contains at least one active assessment service |
| `notes` | No | Nullable and may be blank |
| `expires_at` | No | Date in `YYYY-MM-DD` format, today or later. Omission/null means no expiry. Applies to the whole composite. |
| `is_complimentary` | No | Defaults to `true` |
| `is_credit` | No | Defaults to `false`; cannot be true with `is_complimentary=true`. |
| `credit_received` | Conditional | Required and non-null for credit creation; otherwise optional/null. Nonnegative decimal with 10 total digits and 2 decimal places; zero allowed, no price cap. |
| `price` | Conditional | Required when `is_complimentary` is `false` |
| `redeemable_centers` | Conditional | Optional/empty for global therapy coverage; required for scoped coverage and templates without therapy. Every selected center must be active and assigned to the profile. |
| `therapy_redemption_is_global` | No | Explicit false requires nonempty `redeemable_centers`; true ignores supplied parent centers. When omitted, defaults to true with empty/omitted centers or false with nonempty centers. |
| `therapy_services` | No | Omitted/empty/partial allowed. Each supplied entry requires a unique catalogue therapy ID from the active template; nested centers are optional/empty. Missing selections store empty centers. Explicit centers must be eligible. Null lists are invalid. |
| `created_date` | No | Defaults on the backend when omitted |

The backend derives service membership and session counts from the template.
The frontend sends only per-therapy center selections in `therapy_services`.
The same contract applies to `POST /centers/<center_id>/composite-programs/`,
which also requires `profile_id` and derives the owning center from the URL.

### Center selection flow

1. Load the template's therapy rows using `GET /programs/composites/templates/<template_id>/services/?category=therapy&active=1`. Display `quantity` as read-only sessions and retain nested `service.id` for submission. With no `center_id` parameters, top-level `centers` is an empty array.
2. Load `GET /profiles/<profile_id>/centers/`. Omitted `active` or `active=1` shows active centers; `active=0` shows inactive centers. Assignment rows of either activity state remain included. Use each row's `center.id`, not the assignment row's `id`. Creation still rejects inactive customer assignments.
3. Select program `redeemable_centers`, then reload template therapy rows using repeated parameters: `?category=therapy&active=1&center_id=A&center_id=B`.
4. Each row's top-level `centers` contains the complete matching active service-center choices, without a three-center preview limit. Existing catalogue count fields remain catalogue totals, not the number of filtered choices. Service rows remain paginated; load additional pages as needed to select therapies.
5. Keep services with `centers: []` visible and allow submission without selecting centers. When program centers change, discard incompatible service selections and reload choices. Global service restrictions can use the client's active center IDs as the listing input.
6. Submit any optional therapy selections with fixed template sessions omitted from the request. The backend validates explicit selections before creating all active template therapies. Missing selections produce empty centers, so scoped therapies remain non-redeemable.

Example template-list response excerpt (other existing fields omitted):

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<template_line_id>",
      "service": {"id": "<catalogue_therapy_service_id>", "name": "Therapy"},
      "quantity": 2,
      "service_category_code": "therapy",
      "centers": [{"id": "<center_id>", "code": "CTR01", "name": "Center"}]
    }
  ]
}
```

`description` is not a POST field. It is available only through the limited
composite-program PATCH contract.

### Success response

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<composite_program_uuid>",
    "profile": "<profile_object>",
    "center": "<center_object>",
    "composite_template": "<composite_template_object>",
    "name": "<string|null>",
    "assessment_type": "<Baseline|null>",
    "assessment_type_code": "<baseline|null>",
    "program_type": "composite",
    "notes": "<string|null>",
    "description": "<program_description|null>",
    "expires_at": "<date|null>",
    "is_complimentary": true,
    "is_credit": false,
    "credit_received": null,
    "price": "<decimal_string|null>",
    "redeemable_centers": ["<center_object>"],
    "redeemable_centers_count": 1,
    "services": ["<program_service_object>"],
    "services_count": 1,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 0,
    "consultation_services_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "<date>",
    "is_active": true,
    "created_at": "<datetime>",
    "updated_at": "<datetime>",
    "created_by": "<user_object>"
  }
}
```

Nested objects use the same structures documented in the GET response.

## 6. PATCH — Update Composite Program

### Endpoint

```http
PATCH /programs/composites/programs/:composite_program_id/
```

### Allowed request fields

PATCH is partial. Send only changed values and at least one of these fields:

```json
{
  "notes": "<string|null>",
  "expires_at": "<date|null>",
  "description": "<program_description|null>"
}
```

Examples of valid partial payloads:

```json
{
  "notes": "Customer requested morning sessions."
}
```

```json
{
  "expires_at": "2026-12-31",
  "description": "Updated customer-specific program description."
}
```

### PATCH restrictions

Only the following program fields may change:

- `notes`
- `expires_at`
- `description`
- `therapy_redemption_is_global`
- `redeemable_centers` (parent coverage selections)

The frontend must never submit any of these fields through PATCH:

- `services` or any service/session field
- `composite_template_id` or `composite_template`
- `name`, `assessment_type`, or `assessment_type_code`
- `profile`, `profile_id`, or customer identity fields
- `center` or owning-center fields
- `is_complimentary`, `is_credit`, `credit_received`, or `price`
- counts, cancellation fields, status, creator, or timestamps

Updating top-level `description` changes only
`composite_program.program.description`. It must not update
`composite_template.description`, `name`, `assessment_type`, or
`template_description`.

### Success response

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "<composite_program_uuid>",
    "profile": "<profile_object>",
    "center": "<center_object>",
    "composite_template": "<composite_template_object>",
    "name": "<string|null>",
    "assessment_type": "<Baseline|null>",
    "assessment_type_code": "<baseline|null>",
    "program_type": "composite",
    "notes": "<updated_string|null>",
    "description": "<updated_program_description|null>",
    "expires_at": "<updated_date|null>",
    "is_complimentary": true,
    "is_credit": false,
    "credit_received": null,
    "price": "<decimal_string|null>",
    "redeemable_centers": ["<center_object>"],
    "redeemable_centers_count": 1,
    "services": ["<unchanged_program_service_object>"],
    "services_count": 1,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 0,
    "consultation_services_count": 0,
    "cancellation_reason": "<string|null>",
    "cancelled_by": "<user_object|null>",
    "cancelled_at": "<datetime|null>",
    "cancelled_date": "<date|null>",
    "created_date": "<date>",
    "is_active": true,
    "created_at": "<datetime>",
    "updated_at": "<datetime>",
    "created_by": "<user_object|null>"
  }
}
```

## 7. Error Response

All errors use the project response envelope:

```json
{
  "detail": "<string|object>"
}
```

When `detail` is an object, the frontend must map its field keys to the relevant
inputs. When it is a string, display it as the fallback notification. Expected
failures include inaccessible profiles, invalid center context, inactive
templates, templates without active services, unavailable services, invalid
redeemable centers, a missing or invalid assessment type when the template
contains an active assessment service, past expiry dates, and a missing price
for a non-complimentary program, conflicting credit/complimentary flags, and missing or invalid initial credit amounts.

Service-selection errors appear under `detail.therapy_services`, keyed by catalogue service UUID:

```json
{
  "detail": {
    "therapy_services": {
      "<catalogue_therapy_service_id>": {
        "centers": ["This service is not available at center <center_id>."]
      }
    }
  }
}
```

## 8. Frontend Requirements

### List state

- Show the composite-program name, assessment type, program description,
  expiry, active/expired state,
  total service count, service-category counts, add-on count, and owning center.
- Provide active and expired filters and preserve pagination in the URL state.
- Treat `services` as a preview, `services_count` as the total, and
  `add_ons_count` as a subset that overlaps the category counts.
- Display a clear empty state when `data` is empty.

### Create state

- Load the profile context from the page route; do not ask the user to select the
  profile again.
- Submit the selected template identifier, program fields, and redeemable center
  identifiers.
- Show the optional name input only for templates containing an active
  assessment service. Require assessment type for those templates.
- Show fixed template session counts and collect optional per-service center selections; allow omitted/empty/partial selections.
- Require price only when the complimentary toggle is off.
- Require a nonnegative initial credit amount when credit is selected; selecting credit requires complimentary to be off.
- Allow a blank expiry, submitting null or omitting the field.

### Edit state

- Render only notes, expiry date, and program description as editable fields.
- Show name, assessment type, template, centers, services, prices, and service
  sessions as read-only.
- Build PATCH payloads from changed editable fields only.
- Never submit the complete GET object back to PATCH.
- After success, replace the local program object with the PATCH response data.

## 9. Acceptance Criteria

- GET lists only the selected profile's composite programs and supports active,
  expired, and pagination parameters.
- Profile POST never sends `profile_id`, `center_id`, or service membership/session overrides. `therapy_services` and nested `centers` are optional.
- POST allows name to be omitted or null and conditionally requires assessment
  type for templates containing an active assessment service.
- POST renders field-level backend validation errors correctly.
- Both creation routes accept optional/null/today/future expiry and reject past or malformed dates.
- Both routes support initial credit, including zero, and expose credit fields in create/list/detail responses without creating receipts.
- Both creation routes accept omitted/empty therapy lists, partial lists, and omitted/empty nested centers while creating every active template therapy with fixed sessions and no inherited centers.
- Scoped assignments reject duplicate, non-therapy, foreign-template, and unavailable explicit service-center selections before any records are written. Missing IDs within supplied entries and null lists remain invalid.
- Scoped therapies with empty centers expose `can_redeem: false` and cannot redeem; existing global dynamic eligibility is preserved.
- Global empty restrictions retain dynamic coverage. Center choices remain complete beyond three matches, and unavailable therapy rows remain visible.
- PATCH uses `/programs/composites/programs/:composite_program_id/`.
- PATCH submits only notes, expiry, and/or program description.
- Editing the program description does not alter template metadata.
- Services and service sessions cannot be edited from any screen in this flow.
- All four composite-specific counters are displayed from the API response and
  are never calculated or submitted by the frontend.
- Successful POST and PATCH responses update the UI without requiring the
  frontend to reconstruct nested program data.
