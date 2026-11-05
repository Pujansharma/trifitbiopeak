# Composite Service Assignment — ePRD

Authenticated endpoints use Bearer tokens.

Staff flow: select template → select profile centers → optionally select centers per therapy → assign.
Use `X-Center-ID: <assigning_center_id>` for assignment. GET lists support `page` and `limit` (maximum 50); load all needed pages. Response excerpts below show only fields used in this flow.

## 1. Get composite templates

GET (Authenticated): `<baseURL>/programs/composites/templates/?active=1`

| Query | Value |
| --- | --- |
| `active` | `1` for active templates. |
| `search` | Optional template name/code search. |

**200 OK — response excerpt:**

```json
{
  "data": [
    {
      "id": "<template_id>",
      "name": "Annual Program",
      "assessment_services_count": 1,
      "therapy_services_count": 2
    }
  ]
}
```

Select `data[].id` as `composite_template_id`.

## 2. Get the profile's assigned centers

GET (Authenticated): `<baseURL>/profiles/<profile_id>/centers/`

| Query | Value |
| --- | --- |
| `active` | Omit or `1`: active centers; `0`: inactive. |
| `search` | Optional center-name search. |

**200 OK — response excerpt:**

```json
{
  "data": [
    {
      "id": "<assignment_id>",
      "center": {"id": "<center_id>", "name": "Home Center"},
      "is_primary": true
    }
  ]
}
```

`is_primary=true` identifies the home center. Select one or more `center.id` values for `redeemable_centers`; do not use the assignment ID. Inactive client assignments can appear; creation requires active assignments.

## 3. Get template therapies with matching center choices

GET (Authenticated): `<baseURL>/programs/composites/templates/<template_id>/services/?category=therapy&active=1&center_id=<center_A>&center_id=<center_B>`

| Query | Value |
| --- | --- |
| `category` | `therapy`. |
| `active` | `1` for active template entries/services. |
| `center_id` | Repeat once per selected program center. |
| `search` | Optional therapy-name search. |

**200 OK — response excerpt:**

```json
{
  "data": [
    {
      "id": "<template_line_id>",
      "service": {"id": "<therapy_service_id>", "name": "Therapy"},
      "quantity": 2,
      "centers": [{"id": "<center_A>", "code": "CTR01", "name": "Home Center"}]
    }
  ]
}
```

Display `quantity` as fixed sessions. When selecting therapy centers, submit `service.id`, not the template-line ID, and use top-level `centers[].id`. No `center_id` parameters means empty choices; `centers: []` does not block assignment. Changing program centers requires clearing invalid selections and reloading. Choices are not truncated.

## 4. Assign the composite program

POST (Authenticated): `<baseURL>/profiles/<profile_id>/programs/composite-programs/`

```json
{
  "composite_template_id": "<template_id>",
  "name": "Annual Program",
  "assessment_type": "annual",
  "notes": "",
  "created_date": "2026-10-30",
  "expires_at": "2027-01-30",
  "is_complimentary": false,
  "is_credit": true,
  "price": "12000.00",
  "credit_received": "3000.00",
  "redeemable_centers": [{"id": "<center_A>"}, {"id": "<center_B>"}],
  "therapy_services": [
    {"id": "<therapy_service_1_id>", "centers": [{"id": "<center_A>"}]},
    {"id": "<therapy_service_2_id>", "centers": [{"id": "<center_B>"}]}
  ]
}
```

- `therapy_services` is optional and may be empty or partial. Any supplied centers must come from step 3. Do not send session counts or `therapy_service_centers`.
- All active template therapies are created with fixed sessions. An omitted therapy, omitted nested `centers`, or `centers: []` stores empty centers; no parent-center inheritance. Supplied entries require `id`; null lists remain invalid.
- Scoped therapies with empty centers return `can_redeem: false` and cannot redeem. Assigning centers later still requires the usual eligibility checks.
- `assessment_type` is required only for templates containing assessment services; `name`, `notes`, and `created_date` are optional.
- `expires_at` is optional/null; a supplied date must be today or later.
- Complimentary defaults true; credit defaults false. Both cannot be true. Non-complimentary requires `price`; credit also requires nonnegative `credit_received` (zero allowed, 10 digits/2 decimals, no price cap).
- For global therapy coverage, send `therapy_redemption_is_global: true`; parent centers are ignored and per-therapy restrictions may be empty/omitted.

Optional selection examples (other program fields omitted):

```json
{
  "redeemable_centers": [{"id": "<center_A>"}],
  "therapy_services": [
    {"id": "<therapy_service_1_id>"},
    {"id": "<therapy_service_2_id>", "centers": []},
    {"id": "<therapy_service_3_id>", "centers": [{"id": "<center_A>"}]}
  ]
}
```

Omitting `therapy_services` entirely or sending `[]` also creates every therapy with empty centers. Global empty-center therapies retain dynamic eligibility rather than automatically returning false.

**201 Created — response excerpt:**

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<assigned_composite_program_id>",
    "expires_at": "2027-01-30",
    "is_credit": true,
    "credit_received": "3000.00"
  }
}
```

Service selection failures return **400** under `detail.therapy_services`, keyed by catalogue service ID. Other validation errors use their payload field names.

Center-based alternative: POST `<baseURL>/centers/<center_id>/composite-programs/` with the same payload plus `profile_id`; associates require a matching `X-Center-ID` and Packages permission.
