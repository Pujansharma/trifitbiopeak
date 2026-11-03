# Supplementation plan — shipped schema and API

This file describes the supplementation API that is implemented. A new endpoint gets a tracker row and a contract when it ships.

Envelope on every response: `{ "detail": "...", "data": ... }`. Payloads below are `data`. Paginated lists use `page` and `limit` (default 10, max 50).

Staff means admin or associate (`IsAdminUser | IsAssociateUser`). No `X-Center-ID`. A customer JWT on a staff route is 403. Customer means customer JWT (`IsCustomerUser`). A staff JWT on a plan route is 403. Profile comes from `X-Customer-Profile-ID` and must belong to that user.

Add a supplement only while `ProtocolVersion.status` is `draft`. Edit, replace, and delete a supplement while the status is `draft` or `under_review`. Approve accepts `draft` or `under_review` and requires at least one supplement. Omitted or null `ends_on` on approve stores `starts_on` plus 90 days. That date, and any sent `ends_on`, must be today or later. Publish accepts `approved` only, requires at least one supplement, and requires `starts_on`. Items stay fixed once the version is no longer `draft` or `under_review`. `ends_on` on a `scheduled` or `active` version can move later through extend. Every other status, including `expired` and `cancelled`, cannot be extended.

`GET /supplementation/profiles/` and `GET /supplementation/plan/summary/` bucket the current version:

- Stored `scheduled`, `starts_on` on or before today, and (`ends_on` is null or `ends_on` on or after today) counts as active. The profile list reports that row's `status` as `active`.
- Stored `scheduled` with `starts_on` after today counts as coming up, unless `ends_on` is already before today. That row is historical.
- Stored `approved` or `draft` counts as preparing on the summary only. The profile list omits both.
- A protocol with no `current_version`, and an active `draft` version, counts as preparing on the summary only. A later draft on a protocol that already has a current version does not add a second count.
- Stored `superseded`, `expired`, or `cancelled`, or a stored `active` or `scheduled` version whose `ends_on` is before today, counts as historical.
- `under_review` is omitted.

`GET /supplementation/plan/protocols/` and `GET /supplementation/plan/routine/` use the stored status. They do not apply those buckets.

## Models

Every model has `id` (uuid7), `is_active`, `created_at`, `updated_at` from `BaseUUIDModel`.

### Catalogue

| Model | Role |
|---|---|
| `Brand` | Unique brand name (`Lower(name)`) |
| `Supplement` | Branded product. Unique `Lower(sku)`. Unique `Lower(product_name)` per brand |
| `SupplementActiveIngredient` | Ingredient rows. `serving` is a decimal (`max_digits=12`, `decimal_places=4`) |
| `SupplementAllergen` | Allergen rows. Unique `(supplement, name)`. API key `type` maps to `presence_type` |

`Supplement.form`: `capsule`, `tablet`, `softgel`, `powder`, `liquid`, `gummy`, `lozenge`, `oil`, `cream`, `spray`, `other`.

`raw_material_source_type`: `synthetic`, `natural`, `whole food`, `fermented`, `blended`. `whole food` uses a space.

`dietary_attributes`: `vegan`, `vegetarian`, `gluten_free`, `dairy_free`, `soy_free`, `non_gmo`, `organic`, `kosher`, `halal`, `nut_free`, `corn_free`, `sugar_free`.

Allergen `name`: `gluten`, `dairy`, `soy`, `tree_nuts`, `peanuts`, `shell_fish`, `fish`, `sesame`, `corn`, `wheat`.

Allergen `type`: `contains`, `in_facility`.

`Supplement` also stores `created_by` (`User`, null, `SET_NULL`). `SupplementActiveIngredient` stores `position`.

### `ClientConstraint`

Read on the profile list and profile detail. No write route.

| Column | Type | Relation |
|---|---|---|
| `customer_profile` | FK | `CustomerProfile` PROTECT |
| `kind` | enum | `allergy`, `dietary`, `medical`, `preference` |
| `name` | text | |
| `severity` | text, null | |
| `notes` | text, null | |
| `created_by` | FK, null | `User` SET_NULL |

### `Protocol`

Name and purpose live on the protocol. Dates live on the version.

| Column | Type | Relation |
|---|---|---|
| `customer_profile` | FK | `CustomerProfile` PROTECT |
| `name` | text | |
| `purpose` | text | |
| `current_version` | FK, null | `ProtocolVersion` SET_NULL. Set on publish |
| `created_by` | FK, null | `User` SET_NULL |

### `ProtocolVersion`

Unique `(protocol, version_number)`. At most one `active` row per protocol (`uniq_protocol_one_active`).

| Column | Type | Relation |
|---|---|---|
| `protocol` | FK | `Protocol` PROTECT |
| `version_number` | int | |
| `status` | enum | `draft`, `under_review`, `approved`, `scheduled`, `active`, `superseded`, `expired`, `cancelled` |
| `notes` | text, null | |
| `starts_on` | date, null until approve | |
| `ends_on` | date, null | |
| `review_on` | date, null | |
| `is_ongoing` | bool | default false |
| `summary_notes` | text, null | |
| `supersedes` | FK, null | `ProtocolVersion` SET_NULL. Set on publish |
| `approved_at` | datetime, null | |
| `approved_by` | FK, null | `User` SET_NULL |
| `published_at` | datetime, null | |
| `published_by` | FK, null | `User` SET_NULL |
| `approval_notes` | text, null | |
| `cancelled_at` | datetime, null | |
| `cancelled_by` | FK, null | `User` SET_NULL |
| `cancellation_reason` | text, null | |

### `ProtocolItem`

Unique `(version, supplement)` (`uniq_protocol_item_version_supplement`). `frequency` and `timing` are check-constrained to the values below.

| Column | Type | Relation |
|---|---|---|
| `version` | FK | `ProtocolVersion` CASCADE. Request key `version_id` |
| `supplement` | FK | `Supplement` PROTECT. Request key `supplement_id`. Response is `supplement`: `{id, product_name, brand_name, form}` |
| `dosage` | text | |
| `frequency` | text | `daily`, `twice_daily`, `thrice_daily`, `every_otherday`, `weekly`, `custom`, `as_needed` |
| `custom_frequency` | text, null | Required when `frequency` is `custom`. Null otherwise |
| `timing` | text | `before_breakfast`, `with_breakfast`, `with_lunch`, `with_dinner`, `after_dinner`, `anytime` |
| `duration` | text | |
| `instructions` | text | |
| `rationale` | text | |

### `ProtocolEvent`

No `protocol_item` column. `client_title`, `client_reason`, `change_type`, `effective_on`, and `notes` stay null on every event the current writers create.

| Column | Type | Relation |
|---|---|---|
| `customer_profile` | FK | `CustomerProfile` PROTECT |
| `protocol` | FK, null | `Protocol` SET_NULL |
| `protocol_version` | FK, null | `ProtocolVersion` SET_NULL |
| `actor` | FK, null | `User` SET_NULL |
| `action` | enum | see below |
| `reason` | text, null | set on supplement edit and delete |
| `notes` | text, null | |
| `before` | JSON, null | |
| `after` | JSON, null | |
| `client_visible` | bool | default false |
| `client_title` | text, null | |
| `client_reason` | text, null | |
| `change_type` | enum, null | `added`, `removed`, `replaced`, `modified`, `started`, `stopped` |
| `effective_on` | date, null | |

`action` choices: `protocol_created`, `protocol_renamed`, `version_drafted`, `submitted_for_review`, `approved`, `published`, `scheduled`, `superseded`, `cancelled`, `extended`, `supplement_added`, `supplement_removed`, `supplement_replaced`, `supplement_modified`, `recommendation_accepted`, `recommendation_rejected`, `recommendation_modified`, `batch_completed`, `constraint_added`, `constraint_updated`, `constraint_removed`.

Writers emit `protocol_created`, `version_drafted`, `supplement_added`, `supplement_modified`, `supplement_removed`, `supplement_replaced`, `approved`, `published`, `scheduled`, `superseded`, `cancelled`, and `extended`.

### AI recommendation

`ProtocolAiJob` is the outbox row. `AiRecommendation` is written by the worker. `AiRecommendationItem` is one supplement decision.

| Column | Type | Relation |
|---|---|---|
| `ProtocolAiJob.customer_profile` | FK | `CustomerProfile` PROTECT |
| `requested_by` | FK, null | `User` SET_NULL |
| `name`, `purpose`, `notes` | text | Copied onto the recommendation |
| `supplement_ids` | uuid array | Catalogue ids from the queue body |
| `status` | text | `pending`, `processing`, `completed`, `failed` |
| `attempt_count` | int | Max 2. One try and one retry |
| `error_detail` | text | Last failure |
| `AiRecommendation.job` | one-to-one | `ProtocolAiJob` PROTECT |
| `model` | text | Name returned by Luma |
| `status` | text | `under_review`, then `applied` |
| `protocol_version` | FK, null | Set when the draft is created |
| `AiRecommendationItem.origin` | text | `requested`, `ai_added` |
| `decision` | text | `pending`, `accepted`, `rejected`, `modified` |
| dose columns | text | AI original: `dosage`, `frequency`, `custom_frequency`, `timing`, `duration`, `instructions`, `rationale` |
| `final_*` | text, null | Set on accept or modify. Draft copies these |
| `reason` | text, null | Reject or modify reason |

The worker calls Luma `POST {LUMA_BASE_URL}/luma/v1/integrations/nexus/clients/<customer_profile_id>/protocol-recommendation` with `X-API-Key: LUMA_NEXUS_API_KEY`, timeout 60s. Those two values are Django settings, loaded from `DEV_` / `STG_` / `PRD_` `LUMA_BASE_URL` and `LUMA_NEXUS_API_KEY`. Blank URL or key fails the job with "Luma is not configured." Body: `customer_profile_id`, `metsights_profile_id` (main profile hint, else null), `name`, `purpose`, `notes`, `supplements[]` (id, product, brand, form, serving, ingredients, allergens), `constraints[]` (active only). Response: `model`, `items[]` with `supplement_id`, dose fields, and `origin`. Every requested id must come back. Extra ids must be active catalogue products and are stored as `ai_added`. A bad response fails the job. Non-2xx maps by status only (Luma's error body is never read): 401 "Luma rejected the Nexus API key.", 404 "Luma could not find this client.", 409 "Luma could not confirm this client's identity.", 422 "Luma could not build a recommendation for this client.", anything else, a timeout or a connection error "Luma is unavailable." One try and one retry. The second failure stays `failed`. A request or save error marks that job `failed` and the worker continues with the next job.

## API tracker — Admin FE

| Status | Done | Method | URL | Purpose |
|---|---|---|---|---|
| done | 2026-10-12 | GET | `/supplementation/master/` | Searchable product catalogue |
| done | 2026-10-12 | POST | `/supplementation/master/new-supplement/` | Add a branded product |
| done | 2026-10-26 | GET | `/supplementation/master/<uuid:pk>/` | One product plus ingredients and allergens |
| done | 2026-10-26 | GET | `/supplementation/profiles/` | Staff client list: profile, constraints, active protocol, counts |
| done | 2026-10-28 | GET | `/supplementation/profiles/<uuid:profile_id>/` | Client page: profile, constraints, protocol count |
| done | 2026-10-26 | POST | `/supplementation/profiles/<uuid:profile_id>/protocols/` | Create protocol and draft v1 |
| done | 2026-10-29 | POST | `/supplementation/profiles/<uuid:profile_id>/protocols/ai/` | Queue an AI recommendation job |
| done | 2026-10-29 | GET | `/supplementation/ai-recommendations/` | Review list with decision counts |
| done | 2026-10-29 | GET | `/supplementation/ai-recommendations/<uuid:pk>/` | One recommendation and its items |
| done | 2026-10-29 | POST | `/supplementation/ai-recommendation-items/<uuid:pk>/accept/` | Accept one item |
| done | 2026-10-29 | POST | `/supplementation/ai-recommendation-items/<uuid:pk>/reject/` | Reject one item |
| done | 2026-10-29 | PATCH | `/supplementation/ai-recommendation-items/<uuid:pk>/` | Edit one item. Accept or reject is still required |
| done | 2026-10-29 | POST | `/supplementation/ai-recommendations/<uuid:pk>/draft/` | New protocol and draft v1 from accepted items |
| done | 2026-10-26 | GET | `/supplementation/profiles/<uuid:profile_id>/protocols/` | Every protocol and every version for one profile |
| done | 2026-10-26 | GET | `/supplementation/profiles/<uuid:profile_id>/protocols/current-versions/` | Listed version of every protocol that has one |
| done | 2026-10-26 | GET | `/supplementation/protocols/<uuid:pk>/` | Protocol plus version headers |
| done | 2026-10-26 | GET | `/supplementation/protocols/<uuid:pk>/events/` | Audit for one protocol |
| done | 2026-10-28 | POST | `/supplementation/protocols/<uuid:pk>/versions/` | Next draft. Empty, or a clone of an approved version |
| done | 2026-10-28 | POST | `/supplementation/protocol-versions/<uuid:pk>/items/` | Add a supplement to a draft version |
| done | 2026-10-28 | GET | `/supplementation/protocol-versions/<uuid:pk>/items/` | Supplements on one protocol version |
| done | 2026-10-28 | GET | `/supplementation/protocol-versions/<uuid:pk>/events/` | Audit of changes stored on one version |
| done | 2026-10-28 | PATCH | `/supplementation/protocol-items/<uuid:pk>/` | Edit dosing on a draft or under-review item |
| done | 2026-10-28 | DELETE | `/supplementation/protocol-items/<uuid:pk>/` | Remove a draft or under-review item, keep the reason |
| done | 2026-10-28 | POST | `/supplementation/protocol-items/<uuid:pk>/replace/` | Swap the product on a draft or under-review item |
| done | 2026-10-28 | POST | `/supplementation/protocol-versions/<uuid:pk>/approve/` | `draft` or `under_review` to `approved` |
| done | 2026-10-28 | POST | `/supplementation/protocol-versions/<uuid:pk>/publish/` | `approved` to `scheduled` or `active`. Supersedes every other scheduled or active version of this protocol |
| done | 2026-10-28 | POST | `/supplementation/protocol-versions/<uuid:pk>/cancel/` | `approved`, `scheduled`, or `active` to `cancelled` |
| done | 2026-10-28 | PATCH | `/supplementation/protocol-versions/<uuid:pk>/extend/` | Move `ends_on` later on `scheduled` or `active` |
| done | 2026-10-26 | GET | `/supplementation/profiles/<uuid:profile_id>/events/` | Full audit, including events the client cannot see |

## API tracker — Client FE

| Status | Done | Method | URL | Purpose |
|---|---|---|---|---|
| done | 2026-10-28 | GET | `/supplementation/plan/summary/` | Counts of active, coming up, preparing, and historical protocols |
| done | 2026-10-30 | GET | `/supplementation/plan/routine/` | Supplements on stored `active` versions that have not ended, grouped by timing |
| done | 2026-10-29 | GET | `/supplementation/plan/protocols/` | Stored-status summary plus lists. Each row includes that version's supplements |
| done | 2026-10-29 | GET | `/supplementation/plan/supplement-changes/` | Supplement diff for every protocol with an active or scheduled version |

## Admin FE contracts

### [DONE] GET `/supplementation/master/`

Query: `page`, `limit`, `search` (brand or product name), `form` (`capsule|tablet|softgel|powder|liquid|gummy|lozenge|oil|cream|spray|other`), `active` (`0|1`, omit = both). Junk `form` returns 400 `Invalid form.`

```json
[
  {
    "id": "uuid",
    "product_name": "Vitamin D3",
    "brand_name": "Thorne",
    "form": "capsule",
    "dietary_attributes": ["vegan"],
    "allergen_information": [{"name": "fish", "type": "contains"}]
  }
]
```

### [DONE] POST `/supplementation/master/new-supplement/`

Brand is created when the name is new. Product name is unique per brand. SKU is unique. `market_country_code` is stored uppercased. `serving` on each ingredient is a 4-decimal string. The create response has no `is_active`.

Duplicate SKU: `A supplement with this SKU already exists.` Duplicate product name for the brand: `A supplement with this product name already exists for this brand.`

```json
{
  "brand_name": "Thorne",
  "product_name": "Vitamin D3",
  "form": "capsule",
  "sku": "TD3",
  "manufacturer": "Thorne",
  "raw_material_source_type": "whole food",
  "pack_quantity_info": "60 capsules",
  "serving_size": "1 capsule",
  "serving_container": 60,
  "market_country_code": "US",
  "product_url": "https://example.com/d3",
  "dietary_attributes": ["vegan"],
  "active_ingredients": [
    {
      "ingredient_name": "Cholecalciferol",
      "serving": "5000",
      "unit": "IU",
      "form": "capsule",
      "source": "lichen"
    }
  ],
  "allergen_information": [{"name": "fish", "type": "contains"}]
}
```

```json
{
  "id": "uuid",
  "brand_name": "Thorne",
  "product_name": "Vitamin D3",
  "form": "capsule",
  "sku": "TD3",
  "manufacturer": "Thorne",
  "raw_material_source_type": "whole food",
  "pack_quantity_info": "60 capsules",
  "serving_size": "1 capsule",
  "serving_container": 60,
  "market_country_code": "US",
  "product_url": "https://example.com/d3",
  "dietary_attributes": ["vegan"],
  "active_ingredients": [
    {
      "ingredient_name": "Cholecalciferol",
      "serving": "5000.0000",
      "unit": "IU",
      "form": "capsule",
      "source": "lichen"
    }
  ],
  "allergen_information": [{"name": "fish", "type": "contains"}]
}
```

### [DONE] GET `/supplementation/master/<uuid:pk>/`

Inactive products still load. `serving` is a 4-decimal string.

```json
{
  "id": "uuid",
  "brand_name": "Thorne",
  "product_name": "Vitamin D3",
  "form": "capsule",
  "sku": "TD3",
  "manufacturer": "Thorne",
  "raw_material_source_type": "whole food",
  "pack_quantity_info": "60 capsules",
  "serving_size": "1 capsule",
  "serving_container": 60,
  "market_country_code": "US",
  "product_url": "https://example.com/d3",
  "dietary_attributes": ["vegan"],
  "is_active": true,
  "active_ingredients": [
    {
      "ingredient_name": "Cholecalciferol",
      "serving": "5000.0000",
      "unit": "IU",
      "form": "capsule",
      "source": "lichen"
    }
  ],
  "allergen_information": [{"name": "fish", "type": "contains"}]
}
```

### [DONE] GET `/supplementation/profiles/`

Staff client list. Active profiles only. No `X-Center-ID`.

Query: `page`, `limit`, `search` (first name, last name, or full name, `icontains`; omit or blank = no search), `center` (center UUID of an active center assignment). Unknown `center` returns an empty page. Junk `center` returns 400 `Invalid center.`

Order: latest plan update first, nulls last, then newest profile. `last_updated_on` is the local date of the latest constraint or protocol-version `updated_at`. Null when the profile has neither.

`gender` is the profile label (`Male`, `Female`, `Other`) or null. `age` is whole years, null when date of birth is missing or in the future.

Constraints include inactive rows, ordered by `name`, then `created_at`.

`protocols.active_protocol` is the effective-active current version with the latest `starts_on`, then `updated_at`. Null when none. Its `status` is `active`. A stored `scheduled` version whose window has started is active. Other effective-active protocols on the same profile are not listed.

`coming_up_count`: current versions stored `scheduled` with `starts_on` after today.

`historical_counts`: current versions that are `superseded`, `expired`, `cancelled`, or whose stored status is `active` or `scheduled` and `ends_on` is before today. A superseded version that is not `current_version` is not counted.

Draft, under-review, and approved current versions are omitted from all three.

```json
[
  {
    "customer_profile": {
      "id": "uuid",
      "name": "Ava Shah",
      "gender": "Female",
      "age": 36
    },
    "constraints": [
      {
        "id": "uuid",
        "kind": "allergy",
        "name": "Fish",
        "severity": null,
        "notes": null,
        "is_active": true
      }
    ],
    "last_updated_on": "2026-10-26",
    "protocols": {
      "active_protocol": {
        "id": "uuid",
        "name": "Foundational Health",
        "purpose": "Close nutritional gaps from your blood panel",
        "version_id": "uuid",
        "version_number": 2,
        "status": "active",
        "starts_on": "2026-09-15",
        "ends_on": null,
        "review_on": "2026-12-15"
      },
      "coming_up_count": 1,
      "historical_counts": 2
    }
  }
]
```

### [DONE] GET `/supplementation/profiles/<uuid:profile_id>/`

Staff client page. Admin or associate. No `X-Center-ID`. Active profiles only. Unknown or inactive profile returns 404.

Constraints include inactive rows, ordered by `name`, then `created_at`. There is no `protocols` key. `protocol_count` is every protocol on the profile, including inactive protocols.

`contact_email` is `Customer.contact_email`. `phone` is the account phone, or null. `date_of_birth` is an ISO date or null. `gender` is the label (`Male`, `Female`, `Other`) or null. `name` is first and last name.

```json
{
  "customer_profile": {
    "id": "uuid",
    "name": "Ava Shah",
    "contact_email": "ava@example.com",
    "phone": "+91-9876543210",
    "date_of_birth": "1990-04-12",
    "gender": "Female"
  },
  "constraints": [
    {
      "id": "uuid",
      "kind": "allergy",
      "name": "Fish",
      "severity": null,
      "notes": null,
      "is_active": true
    }
  ],
  "protocol_count": 2
}
```

### [DONE] POST `/supplementation/profiles/<uuid:profile_id>/protocols/`

Staff create. Admin or associate. No `X-Center-ID`. Active profile, else 404. `201`. Detail `Protocol created.` Response matches `GET /supplementation/protocols/<uuid:pk>/`. `current_version_id` stays null until publish. Items are not copied.

Omit `source_version_id` for a blank draft. `name` and `purpose` are required and stored on `Protocol`. `notes` is optional and defaults to `""` on the version. `summary_notes` stays null. `is_ongoing` stays false.

Send `source_version_id` to start a new protocol from that version. The version must belong to a protocol on this profile, else 404 `Protocol version not found.` Any stored status is accepted. `name` and `purpose` are optional overrides stored on the new `Protocol`. Omitted values come from the source protocol. Version fields copied are `notes`, `summary_notes`, and `is_ongoing`. A sent `notes` replaces the copied notes. `starts_on`, `ends_on`, and `review_on` stay null. `supplement_count` is 0.

Writes `protocol_created` and `version_drafted`. Both stay `client_visible` false. `protocol_created.after` is `{name, purpose}`. `version_drafted.after` is `{version_number, status}` and includes `source_version_id` when the draft was copied.

```json
{"name": "Sleep & Recovery", "purpose": "Faster sleep onset and deeper sleep", "notes": ""}
```

```json
{"source_version_id": "uuid", "name": "Sleep & Recovery", "purpose": "Faster sleep onset and deeper sleep", "notes": ""}
```

```json
{
  "id": "uuid",
  "name": "Sleep & Recovery",
  "purpose": "Faster sleep onset and deeper sleep",
  "current_version_id": null,
  "versions": [
    {
      "id": "uuid",
      "version_number": 1,
      "status": "draft",
      "starts_on": null,
      "ends_on": null,
      "review_on": null,
      "supplement_count": 0
    }
  ]
}
```

### [DONE] GET `/supplementation/profiles/<uuid:profile_id>/protocols/`

Staff protocol list for one profile. Admin or associate. No `X-Center-ID`. Active profile, else 404. Paginated with `page` and `limit`.

Every protocol, including inactive protocols, newest `created_at` first, including `draft` and `under_review`. Each row is the protocol detail: `name`, `purpose`, `current_version_id`, and every version header in `version_number` order. `status` is stored. `supplement_count` is the `ProtocolItem` count on that version.

```json
[
  {
    "id": "uuid",
    "name": "Sleep & Recovery",
    "purpose": "Faster sleep onset and deeper sleep",
    "current_version_id": "uuid",
    "versions": [
      {
        "id": "uuid",
        "version_number": 1,
        "status": "draft",
        "starts_on": null,
        "ends_on": null,
        "review_on": null,
        "supplement_count": 0
      }
    ]
  }
]
```

### [DONE] GET `/supplementation/profiles/<uuid:profile_id>/protocols/current-versions/`

Staff picker for copying a protocol. Admin or associate. No `X-Center-ID`. Active profile, else 404. Not paginated.

One row per protocol, including inactive protocols. The row is the highest `version_number` whose status is `approved`, `scheduled`, `active`, `expired`, or `cancelled`. A `superseded` version is the row only when every higher `version_number` is `draft` or `under_review`. `draft` and `under_review` are never the row. A protocol with no such version is omitted. `approved` is listed before publish, so `Protocol.current_version` may be null. Newest protocol `created_at` first. `version_name` is `v` plus `version_number`. `effective_from` is `starts_on`. `status` is the stored status. `id` is the protocol id. Response `current_version_id` is the chosen version. `supplement_count` is the `ProtocolItem` count on that version.

```json
[
  {
    "id": "uuid",
    "current_version_id": "uuid",
    "version_name": "v2",
    "supplement_count": 2,
    "effective_from": "2026-09-15",
    "status": "active"
  }
]
```

### [DONE] GET `/supplementation/protocols/<uuid:pk>/`

Staff protocol page. Admin or associate. No `X-Center-ID`. Unknown id returns 404. An inactive protocol still loads.

`name` and `purpose` are on the protocol. Every version, `version_number` ascending. `status` is the stored value, including `draft` and `under_review`. `supplement_count` is the `ProtocolItem` count on that version. `current_version_id` is null when unset.

```json
{
  "id": "uuid",
  "name": "Sleep & Recovery",
  "purpose": "Faster sleep onset and deeper sleep",
  "current_version_id": "uuid",
  "versions": [
    {
      "id": "uuid",
      "version_number": 1,
      "status": "active",
      "starts_on": "2026-09-15",
      "ends_on": "2026-12-15",
      "review_on": "2026-12-01",
      "supplement_count": 2
    }
  ]
}
```

### [DONE] GET `/supplementation/protocols/<uuid:pk>/events/`

Staff audit for one protocol. Admin or associate. No `X-Center-ID`. Unknown protocol returns 404. An inactive protocol still loads.

This is the profile event list filtered to `protocol_id`. Same row, same order, same query. Rows for other protocols are omitted. Pagination is independent of the profile list.

Query: `page`, `limit` (default 10, max 50), `action`. Junk `action` returns 400 `Invalid action.` Newest `created_at`, then `id`. Includes `client_visible` false.

A stored `supplement_id` in `before` or `after` is replaced in the response by `supplement`: `{id, product_name, brand_name, form}`. The stored JSON keeps `supplement_id`. A missing supplement is `{id, product_name: null, brand_name: null, form: null}`. Other keys in that object stay.

Item payloads (`supplement_added`, `supplement_modified`, `supplement_removed`, `supplement_replaced`) are `supplement_id`, `dosage`, `frequency`, `custom_frequency`, `timing`, `duration`, `instructions`, `rationale`. `supplement_added` has `before` null. `supplement_removed` has `after` null. Edit and delete store `reason`. Replace does not.

`approved`, `published`, `scheduled`, `superseded`, `cancelled`, and `extended` use `{status, starts_on, ends_on, approval_notes}` for `before` and `after`. Cancel stores the text on `ProtocolVersion.cancellation_reason`, not on `ProtocolEvent.reason`.

`client_title`, `client_reason`, `change_type`, and `effective_on` are null.

```json
[
  {
    "id": "uuid",
    "action": "supplement_modified",
    "reason": "Dose raised after the repeat panel.",
    "client_visible": false,
    "client_title": null,
    "change_type": null,
    "effective_on": null,
    "protocol_id": "uuid",
    "protocol_version_id": "uuid",
    "before": {
      "supplement": {
        "id": "uuid",
        "product_name": "Vitamin D3",
        "brand_name": "Thorne",
        "form": "capsule"
      },
      "dosage": "1 capsule",
      "frequency": "daily",
      "custom_frequency": null,
      "timing": "with_breakfast",
      "duration": "30 days",
      "instructions": "Take 1 capsule with your morning meal.",
      "rationale": "25(OH)D was 32 ng/mL."
    },
    "after": {
      "supplement": {
        "id": "uuid",
        "product_name": "Vitamin D3",
        "brand_name": "Thorne",
        "form": "capsule"
      },
      "dosage": "2 capsules",
      "frequency": "daily",
      "custom_frequency": null,
      "timing": "with_lunch",
      "duration": "60 days",
      "instructions": "Take 2 capsules with lunch.",
      "rationale": "25(OH)D was 32 ng/mL."
    },
    "created_at": "2026-09-20T10:00:00+05:30"
  }
]
```

### [DONE] GET `/supplementation/protocol-versions/<uuid:pk>/events/`

Staff audit for one protocol version. Admin or associate. No `X-Center-ID`. Unknown version returns 404 `Protocol version not found.` An inactive protocol still loads.

This is the protocol event list filtered to `protocol_version_id`. Same row, same order, same query. Rows for other versions are omitted. A `superseded` row stored on the replaced version appears on that version. Pagination is independent of the protocol list.

Query: `page`, `limit` (default 10, max 50), `action`. Junk `action` returns 400 `Invalid action.` Newest `created_at`, then `id`. Includes `client_visible` false. `before` and `after` follow the protocol event list.

### [DONE] POST `/supplementation/protocols/<uuid:pk>/versions/`

Staff next draft on an existing protocol. Admin or associate. No `X-Center-ID`. Unknown protocol returns 404. An inactive protocol still loads. `201`. Detail `Protocol version created.`

Omit `source_version_id` for an empty draft. Send `source_version_id` to clone items from that version. The source must belong to a protocol on the same customer profile, else 404 `Protocol version not found.` The source status must be `approved`, `scheduled`, `active`, `superseded`, `expired`, or `cancelled`. `draft` or `under_review` returns 400 `Protocol version can only be copied once it is approved.`

`summary_notes` is optional. Omit it, or send a blank value, and the column stores null. `notes` stays null. Dates stay null. `is_ongoing` stays false. The new row is `draft`. `version_number` is one past the highest number on this protocol. `current_version` stays. `name` and `purpose` stay on the protocol. Writes one `version_drafted` event, `client_visible` false. `after` is `{version_number, status}` and includes `source_version_id` only when items were cloned.

```json
{"summary_notes": "Reset after the April panel"}
```

```json
{"source_version_id": "uuid", "summary_notes": "Cloned from the active plan"}
```

```json
{"new_protocol_version_id": "uuid"}
```

### [DONE] POST `/supplementation/protocol-versions/<uuid:pk>/items/`

Staff add a supplement to one protocol version. Draft only. 201. Detail `Supplement added to protocol version.` Unknown version returns 404 `Protocol version not found.` Unknown supplement returns 404 `Supplement not found.` Inactive supplement returns 400 `Supplement is inactive.` on `supplement_id`. The same supplement already on this version returns 400 `This supplement is already on this version.` on `supplement_id`. A concurrent unique clash returns that same 400. One version holds each supplement once. The same product on another version is allowed.

`version_id` must equal the path id, else 400 `version_id does not match this protocol version.` Any status other than `draft` returns 400 `Supplements can only be added while the version is draft.` on `version_id`.

`frequency` `custom` requires `custom_frequency` (`This field is required when frequency is custom.`). Any other frequency requires `custom_frequency` null (`custom_frequency must be null unless frequency is custom.`). Any other `timing` returns 400. Writes `supplement_added`, `client_visible` false. `before` is null. `after` is the item payload.

```json
{
  "version_id": "uuid",
  "supplement_id": "uuid",
  "dosage": "1 capsule",
  "frequency": "daily",
  "custom_frequency": null,
  "timing": "with_breakfast",
  "duration": "30 days",
  "instructions": "Take 1 capsule with your morning meal.",
  "rationale": "25(OH)D was 32 ng/mL."
}
```

`frequency`: `daily`, `twice_daily`, `thrice_daily`, `every_otherday`, `weekly`, `custom`, `as_needed`.

`timing`: `before_breakfast`, `with_breakfast`, `with_lunch`, `with_dinner`, `after_dinner`, `anytime`.

`supplement_id` is request-only. Response `supplement` is `{id, product_name, brand_name, form}`. `form` is the stored code.

```json
{
  "id": "uuid",
  "version_id": "uuid",
  "supplement": {
    "id": "uuid",
    "product_name": "Vitamin D3",
    "brand_name": "Thorne",
    "form": "capsule"
  },
  "dosage": "1 capsule",
  "frequency": "daily",
  "custom_frequency": null,
  "timing": "with_breakfast",
  "duration": "30 days",
  "instructions": "Take 1 capsule with your morning meal.",
  "rationale": "25(OH)D was 32 ng/mL."
}
```

### [DONE] GET `/supplementation/protocol-versions/<uuid:pk>/items/`

Staff list of supplements on that version. Not paginated. Oldest `created_at`, then `id`. Unknown version returns 404 `Protocol version not found.` Empty version returns `data: []`. Each row matches the add response. Detail `Protocol supplements retrieved.`

### [DONE] PATCH `/supplementation/protocol-items/<uuid:pk>/`

Staff edit dosing on one supplement. Admin or associate. A customer receives 403. No `X-Center-ID`. No `X-Customer-Profile-ID`. `draft` or `under_review` only. Any other status returns 400 `Supplements can only be changed while the version is draft or under review.` Unknown item returns 404 `Protocol supplement not found.`

`supplement_id` and `rationale` stay. `reason` is required and is stored on `ProtocolEvent.reason`. Blank `reason` returns 400. `frequency` and `timing` rules match add. Writes `supplement_modified`, `client_visible` false. `before` and `after` are the item payload. 200. Detail `Supplement updated on protocol version.` `data` matches the add response. `reason` is not in `data`.

```json
{
  "dosage": "2 capsules",
  "frequency": "daily",
  "custom_frequency": null,
  "timing": "with_lunch",
  "duration": "60 days",
  "instructions": "Take 2 capsules with lunch.",
  "reason": "Dose raised after the repeat panel."
}
```

### [DONE] DELETE `/supplementation/protocol-items/<uuid:pk>/`

Staff remove one supplement. Admin or associate. A customer receives 403. Same status gate and 404 as the edit. Body is `reason` only. `reason` is required and is stored on `ProtocolEvent.reason`. The row is deleted. Writes `supplement_removed`, `client_visible` false. `before` is the item payload. `after` is null. `data` omitted.

```json
{"reason": "Levels normalized on blood panel"}
```

```json
{"detail": "Supplement removed from protocol version."}
```

### [DONE] POST `/supplementation/protocol-items/<uuid:pk>/replace/`

Staff swap the product on the same row. Admin or associate. A customer receives 403. Same status gate and 404 as the edit. Body matches the add payload. `version_id` must equal that item's version, else 400 `version_id does not match this protocol version.` Unknown supplement returns 404 `Supplement not found.` Inactive supplement returns 400 `Supplement is inactive.` A product already on another row of this version returns 400 `This supplement is already on this version.` A concurrent unique clash returns that same 400. Keeping the product already on this row is allowed. `frequency` and `timing` rules match add. Writes `supplement_replaced`, `client_visible` false. `before` and `after` are the item payload. `reason` stays null. 200. Detail `Supplement replaced on protocol version.` `data` matches the add response.

```json
{
  "version_id": "uuid",
  "supplement_id": "uuid",
  "dosage": "2 softgels",
  "frequency": "daily",
  "custom_frequency": null,
  "timing": "with_lunch",
  "duration": "90 days",
  "instructions": "Take 2 softgels with your largest meal.",
  "rationale": "Cardiovascular support."
}
```

### [DONE] POST `/supplementation/protocol-versions/<uuid:pk>/approve/`

Staff approve one protocol version. Admin or associate. No `X-Center-ID`. `draft` or `under_review` becomes `approved`. Any other status returns 400 `Protocol version can only be approved while it is draft or under review.` A version with no supplements returns 400 `Add at least one supplement before approving this version.` An inactive supplement on the version returns 400 `Supplement is inactive.` The status update itself requires at least one item and no inactive supplement. Unknown version returns 404 `Protocol version not found.`

`starts_on` is required. `ends_on` may be null. Omit `ends_on`, or send null, and the stored end date is `starts_on` plus 90 days. A sent `ends_on` stays as sent. `ends_on` before `starts_on` returns 400 `ends_on must be on or after starts_on.` `ends_on` before today, including that default, returns 400 `ends_on must be on or after today.` `approval_notes` may be blank; blank stores null. `review_on` and `is_ongoing` stay as already saved. Other versions of this protocol keep their status. `Protocol.current_version` stays put. Sets `approved_at` and `approved_by`. Writes `approved`, `client_visible` false. `before` and `after` are the version window (`status`, `starts_on`, `ends_on`, `approval_notes`).

The summary counts this version as `preparing` until publish. `GET /supplementation/plan/protocols/` omits it.

```json
{
  "starts_on": "2026-10-01",
  "ends_on": "2026-12-15",
  "approval_notes": ""
}
```

`data` omitted.

```json
{"detail": "Protocol version approved."}
```

### [DONE] POST `/supplementation/protocol-versions/<uuid:pk>/publish/`

Staff publish one approved protocol version. Admin or associate. No `X-Center-ID`. The request body is ignored. Unknown version returns 404 `Protocol version not found.` Any other status returns 400 `Protocol version can only be published while it is approved.` A version with no supplements returns 400 `Add at least one supplement before publishing this version.` An inactive supplement on the version returns 400 `Supplement is inactive.` The status update itself requires at least one item and no inactive supplement. A null `starts_on` returns 400 `starts_on is required before publishing this version.`

`starts_on` after today stores `scheduled` and writes `scheduled`. `starts_on` today or earlier stores `active` and writes `published`. Sets `published_at`, `published_by`, and `Protocol.current_version`. Every other `scheduled` or `active` version of this protocol becomes `superseded` in the same transaction. `supersedes` points at the previous `current_version` when that row is one of the versions just superseded. Each superseded version gets a `superseded` event. Those events are `client_visible` true. Existing events on this version flip to `client_visible` true. `before` and `after` on the publish and superseded events are the version window.

A second live `active` row on this protocol returns 400 `This protocol already has an active version.`

`manage.py sweep_protocol_versions` runs from `assets/scripts/sweep_jobs.sh`. It writes no event. Expire runs before activate. `scheduled` or `active` with `ends_on` before today becomes `expired`. The version stays active on `ends_on` itself. Then each protocol with a `scheduled` version whose `starts_on` is on or before today and whose window is still open activates one row: the due `current_version` when that row is due, otherwise the due row with the highest `version_number`. Other due `scheduled` rows on that protocol become `superseded`. Any other `active` version of that protocol becomes `superseded`. A repeat run changes nothing.

`data` omitted.

```json
{"detail": "Protocol version published."}
```

### [DONE] POST `/supplementation/protocol-versions/<uuid:pk>/cancel/`

Staff cancel one protocol version after it is approved. Admin or associate. No `X-Center-ID`. Unknown version returns 404 `Protocol version not found.` `approved`, `scheduled`, or `active` becomes `cancelled`. Any other status returns 400 `Protocol version can only be cancelled after it is approved.` There is no date check.

`reason` is required. Blank or whitespace returns 400. It stores on `cancellation_reason`. Also sets `cancelled_at` and `cancelled_by`. `Protocol.current_version` stays on this row. A superseded predecessor stays superseded. `ProtocolEvent.reason` stays null.

Writes `cancelled`. `before` and `after` are the version window. `client_visible` is false while the version is still `approved`. It is true for `scheduled` and `active`.

`data` omitted.

```json
{"reason": "Protocol ended early"}
```

```json
{"detail": "Protocol version cancelled."}
```

### [DONE] PATCH `/supplementation/protocol-versions/<uuid:pk>/extend/`

Staff move the end date of one protocol version later. Admin or associate. No `X-Center-ID`. Unknown version returns 404 `Protocol version not found.` `scheduled` and `active` keep their status. `expired`, `cancelled`, and every other status return 400 `Protocol version can only be extended while it is scheduled or active.`

`ends_on` is required. It must be on or after `starts_on` (`ends_on must be on or after starts_on.`), on or after today (`ends_on must be on or after today.`), and after the stored `ends_on` (`ends_on must be after the current end date.`). A null stored `ends_on` returns 400 `This version has no end date to extend.` `starts_on` stays. `Protocol.current_version` stays. Items stay.

Writes `extended`, `client_visible` true. `before` and `after` are the version window (`status`, `starts_on`, `ends_on`, `approval_notes`).

`data` omitted.

```json
{"ends_on": "2027-01-15"}
```

```json
{"detail": "Protocol version extended."}
```

### [DONE] GET `/supplementation/profiles/<uuid:profile_id>/events/`

Staff recent activity for one profile. Admin or associate. No `X-Center-ID`. Active profile or 404.

Query: `page`, `limit` (default 10, max 50), `action`. Junk `action` returns 400 `Invalid action.` Newest `created_at`, then `id`. Includes `client_visible` false. A profile with no rows returns an empty page. The row matches the protocol event list.

## Client FE contracts

### [DONE] GET `/supplementation/plan/summary/`

Customer JWT. No `X-Center-ID`. Profile is `X-Customer-Profile-ID` and must belong to that user. Missing header, blank header, junk id, unknown id, another customer's profile, or an inactive profile returns 404 `Customer profile not found.` Detail `Protocol summary retrieved successfully.`

Counts are the current version of each active protocol. `under_review` is omitted. A superseded version that is not `current_version` is omitted. An empty plan returns zeros. Buckets are the rules at the top of this file.

`active`: stored `active` inside its window, or stored `scheduled` whose window includes today.

`coming_up`: stored `scheduled` with `starts_on` after today, and `ends_on` null or on or after today.

`preparing`: stored `approved` or `draft`. A protocol with no `current_version` and an active draft version counts here too.

`historical`: `superseded`, `expired`, `cancelled`, or stored `active` or `scheduled` with `ends_on` before today.

```json
{"active": 2, "coming_up": 1, "preparing": 0, "historical": 3}
```

### [DONE] GET `/supplementation/plan/routine/`

Customer JWT. No `X-Center-ID`. Profile is `X-Customer-Profile-ID`, same 404 as the summary. No body. Detail `Active supplements retrieved successfully.`

Items on versions whose stored status is `active`, whose version is active, whose protocol is active, and whose `ends_on` is null or today or later. A stored `scheduled` version is omitted, including one whose window has started. An `active` version whose `ends_on` is before today is omitted until the sweep marks it `expired`. Groups follow `before_breakfast`, `with_breakfast`, `with_lunch`, `with_dinner`, `after_dinner`, `anytime`. An empty timing is omitted. Inside a timing, items are ordered by product name, then `id`. `ends_on` is that version's end date. `duration` is not on this response. No `protocol` key. An empty plan returns `{"timings": []}`.

```json
{
  "timings": [
    {
      "timing": "with_breakfast",
      "items": [
        {
          "id": "uuid",
          "supplement": {
            "id": "uuid",
            "product_name": "Vitamin D3",
            "brand_name": "Thorne",
            "form": "capsule"
          },
          "dosage": "1 capsule",
          "frequency": "daily",
          "custom_frequency": null,
          "timing": "with_breakfast",
          "ends_on": "2026-12-15",
          "instructions": "Take with food.",
          "rationale": "Low vitamin D on the last panel."
        }
      ]
    }
  ]
}
```

### [DONE] GET `/supplementation/plan/protocols/`

Customer JWT. Same profile header as the summary. No body. Detail `Protocols retrieved successfully.`

`summary` counts one stored status per active protocol, from `current_version`. `active`, `scheduled`, `draft`, `cancelled`, `expired`. A null `current_version` with a `draft` version counts as `draft`. A later unpublished draft does not add a second count. `approved`, `under_review`, and `superseded` are omitted. Inactive protocols are omitted. An inactive `current_version` is omitted and is not counted as `draft`.

Lists are those protocols except `draft`. Newest `starts_on` first, then newest version `updated_at`. A null `starts_on` sorts last. Stored status, including an `active` version whose `ends_on` is already past.

`supplements` is every item on that version. Product name, then item id. `supplement` is `id`, `product_name`, `brand_name`, `form`. Dose fields are `dosage`, `frequency`, `custom_frequency`, `timing`, `duration`, `instructions`, `rationale`. `ends_on` stays on `version`. A version with no items returns `supplements: []`. `supplement_count` is that list's length.

```json
{
  "summary": {
    "active": 1,
    "scheduled": 1,
    "draft": 1,
    "cancelled": 1,
    "expired": 1
  },
  "active": [
    {
      "id": "uuid",
      "name": "Foundational Health",
      "purpose": "Close nutritional gaps from the last panel.",
      "status": "active",
      "supplement_count": 4,
      "version": {
        "id": "uuid",
        "version_number": 3,
        "starts_on": "2026-09-15",
        "ends_on": "2026-12-15"
      },
      "supplements": [
        {
          "id": "uuid",
          "supplement": {
            "id": "uuid",
            "product_name": "Vitamin D3",
            "brand_name": "Thorne",
            "form": "capsule"
          },
          "dosage": "1 capsule",
          "frequency": "daily",
          "custom_frequency": null,
          "timing": "with_breakfast",
          "duration": "90 days",
          "instructions": "Take with food.",
          "rationale": "Low vitamin D on the last panel."
        }
      ]
    }
  ],
  "scheduled": [],
  "cancelled": [],
  "expired": []
}
```

### [DONE] GET `/supplementation/plan/supplement-changes/`

Customer JWT. Same profile header as the summary. No body. No protocol id. Detail `Supplement changes retrieved successfully.` An empty plan returns `data: []`.

One row per active protocol that has an `active` or `scheduled` version. `active` rows first, then `scheduled`, each by name, case-insensitive. If both statuses exist, the row uses the `active` version, even when a `scheduled` version has a higher `version_number`. Otherwise the `scheduled` version with the highest `version_number` is used. `status` is that version.

The diff is that version against `supersedes`. No `supersedes` means there is no previous version: every item on the live version is `added`, and `modified`, `replaced`, and `removed` are empty.

`replaced` is a `supplement_replaced` event on the live version, oldest first, whose old supplement is only on the previous version and whose new supplement is only on the live version. The first event claims each supplement. That pair is not also `added` or `removed`. `modified` is the same supplement with a different `dosage`, `frequency`, `custom_frequency`, `timing`, `instructions`, or `rationale`. A `duration`-only change is not `modified`. `duration` is not in the snapshot.

`modified`, `added`, and `removed` are ordered by product name, then supplement id. `replaced` is ordered by the new product name, then supplement id.

```json
[
  {
    "name": "Foundational Health",
    "status": "active",
    "changes": {
      "modified": [
        {
          "supplement": {
            "id": "uuid",
            "product_name": "Vitamin D3",
            "brand_name": "Thorne",
            "form": "capsule"
          },
          "before": {
            "dosage": "1 capsule",
            "frequency": "daily",
            "custom_frequency": null,
            "timing": "with_breakfast",
            "instructions": "Take with food.",
            "rationale": "Low vitamin D."
          },
          "after": {
            "dosage": "2 capsules",
            "frequency": "daily",
            "custom_frequency": null,
            "timing": "with_breakfast",
            "instructions": "Take with food.",
            "rationale": "Still low on the repeat panel."
          }
        }
      ],
      "replaced": [
        {
          "before": {
            "supplement": {
              "id": "uuid",
              "product_name": "Fish Oil",
              "brand_name": "Thorne",
              "form": "softgel"
            },
            "dosage": "1 capsule",
            "frequency": "daily",
            "custom_frequency": null,
            "timing": "with_lunch",
            "instructions": "Take with food.",
            "rationale": "Low vitamin D."
          },
          "after": {
            "supplement": {
              "id": "uuid",
              "product_name": "Algae Omega-3",
              "brand_name": "Thorne",
              "form": "softgel"
            },
            "dosage": "2 softgels",
            "frequency": "daily",
            "custom_frequency": null,
            "timing": "with_lunch",
            "instructions": "Take with the largest meal.",
            "rationale": "Vegan omega-3."
          }
        }
      ],
      "added": [
        {
          "supplement": {
            "id": "uuid",
            "product_name": "Magnesium Glycinate",
            "brand_name": "Thorne",
            "form": "capsule"
          },
          "dosage": "2 capsules",
          "frequency": "daily",
          "custom_frequency": null,
          "timing": "after_dinner",
          "instructions": "Take in the evening.",
          "rationale": "Sleep support."
        }
      ],
      "removed": []
    }
  }
]
```

### [DONE] POST `/supplementation/profiles/<uuid:profile_id>/protocols/ai/`

Staff queue. Admin or associate. No `X-Center-ID`. 202. Active profile, else 404 `Customer profile not found.` Does not create a protocol. `name` and `purpose` are required. `notes` may be blank. `supplement_ids` is a non-empty list of distinct active catalogue ids. An empty list, a duplicate, an unknown id, or an inactive supplement is 400.

```json
{ "id": "uuid", "status": "pending" }
```

`id` is the job id. The list shows that job immediately with `status` `processing`. `recommendation.id` stays null until the worker saves the result and the model.

### [DONE] GET `/supplementation/ai-recommendations/`

Staff list. One row per job, including jobs the worker has not saved yet. Newest `created_at` first. `created_at` is the queue time. `page` and `limit` default 10, max 50. `search` matches customer first name, last name, full name, or recommendation name. `recommendation_status` is `processing`, `failed`, `pending`, or `completed`. Omit it for all four. Any other value is 400 `Invalid recommendation_status.`

`processing` is a queued or running job. `failed` is a failed job, and `error` is `error_detail`. `pending` includes `processing` rows and saved rows that still have an item `pending` or `modified`. `completed` means every item is `accepted` or `rejected`. `recommendation.id` and `model` are null until the worker saves. Detail stays 404 until `recommendation.id` is set. `id` is the job id from the 202.

```json
[
  {
    "id": "job-uuid",
    "customer_profile": {
      "id": "uuid",
      "name": "Ava Shah",
      "gender": "Female",
      "age": 36
    },
    "recommendation": {
      "id": "uuid",
      "name": "Sleep & Recovery",
      "total": 2,
      "accepted": 1,
      "modified": 0,
      "rejected": 0
    },
    "model": "gpt-4.1",
    "error": null,
    "status": "pending",
    "created_at": "2026-10-29T09:40:00+05:30"
  }
]
```

`modified` counts items edited and not yet accepted or rejected. A queued row has `status` `processing`, null `recommendation.id`, null `model`, null `error`, and zero counts. A failed row has `status` `failed` and `error` set.

### [DONE] GET `/supplementation/ai-recommendations/<uuid:pk>/`

Unknown id is 404 `AI recommendation not found.` `status` is `under_review` or `applied`. `protocol_version_id` is null until draft. Items are oldest first. Dose fields are the AI choice. `final_*` is null until accept or modify. Each item has `supplement`: `{id, product_name, brand_name, form, manufacturer}`. `form` is the stored code. `supplement_id` is not returned.

### [DONE] POST `/supplementation/ai-recommendation-items/<uuid:pk>/accept/`

Body `{}`. Allowed while `pending` or `modified`. Accept with no earlier modify copies the AI dose into `final_*`. Accept after modify keeps the edited dose. Decision becomes `accepted`. Already accepted or rejected is 400 `This item is already accepted or rejected.` Unknown item is 404 `AI recommendation item not found.`

```json
{ "id": "uuid", "decision": "accepted" }
```

### [DONE] POST `/supplementation/ai-recommendation-items/<uuid:pk>/reject/`

`reason` is required. Blank is 400. Decision becomes `rejected`. The supplement stays off the later draft.

```json
{ "id": "uuid", "decision": "rejected" }
```

### [DONE] PATCH `/supplementation/ai-recommendation-items/<uuid:pk>/`

Same dose body as editing a protocol supplement, plus required `reason`. AI dose fields stay. The product and `rationale` stay. The edit is stored on `final_*`. Decision becomes `modified`. `reason` is stored and is omitted from `data`. `data` is the item, with `supplement`: `{id, product_name, brand_name, form, manufacturer}`. `form` is the stored code. `supplement_id` is not returned.

### [DONE] POST `/supplementation/ai-recommendations/<uuid:pk>/draft/`

Body `{}`. 201. Allowed only while `under_review` and every item is `accepted` or `rejected`. A `pending` or `modified` item is 400 `Accept or reject every supplement before creating the draft.` Zero accepted items is 400 `Accept at least one supplement before creating the draft.` A second call is 400 `A draft was already created from this recommendation.` Creates a new protocol and draft version 1. Copies accepted items only, using `final_*`. Recommendation becomes `applied` and stores `protocol_version_id`.

```json
{
  "protocol_id": "uuid",
  "new_protocol_version_id": "uuid",
  "status": "draft"
}
```
