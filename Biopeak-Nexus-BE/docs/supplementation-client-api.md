# Supplementation client API

Every response is `{ "detail": string, "data": object | array }`.

Shared values:

- `supplement.form`: `capsule`, `tablet`, `softgel`, `powder`, `liquid`, `gummy`, `lozenge`, `oil`, `cream`, `spray`, `other`
- `frequency`: `daily`, `twice_daily`, `thrice_daily`, `every_otherday`, `weekly`, `custom`, `as_needed`
- `custom_frequency`: string when `frequency` is `custom`, otherwise `null`
- `timing`: `before_breakfast`, `with_breakfast`, `with_lunch`, `with_dinner`, `after_dinner`, `anytime`
- dates: `YYYY-MM-DD` or `null`
- ids: uuid

## GET `/supplementation/plan/summary/`

Counts of the customer's current protocols: active, coming up, preparing, historical. `preparing` is `approved` plus `draft`. `under_review` is omitted. A protocol with no current version and an active draft counts as preparing.

Request: none

```json
{
  "detail": "Protocol summary retrieved successfully.",
  "data": {
    "active": 2,
    "coming_up": 1,
    "preparing": 0,
    "historical": 3
  }
}
```

## GET `/supplementation/plan/routine/`

Supplements on stored active versions, grouped by timing. Empty timings are omitted. `ends_on` is the version end date.

Request: none

```json
{
  "detail": "Active supplements retrieved successfully.",
  "data": {
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
}
```

## GET `/supplementation/plan/protocols/`

One stored status per protocol, plus lists. `summary.draft` is a count only. Lists are `active`, `scheduled`, `cancelled`, `expired`. `status` on a row is that stored status. `supplement_count` is the item count on `version`. `supplements` is each item on that version: product, brand, form, and dose fields including `duration`. Ordered by product name, then item id.

Request: none

```json
{
  "detail": "Protocols retrieved successfully.",
  "data": {
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
}
```

## GET `/supplementation/plan/supplement-changes/`

One row per protocol with an active or scheduled version. `status` is `active` or `scheduled`. `changes` is that version against the version it replaced.

- `modified`: same supplement, dose fields differ. `before` and `after` are dosage, frequency, custom_frequency, timing, instructions, rationale.
- `replaced`: old supplement swapped for a new one. Each side is a supplement plus those dose fields.
- `added`: on the live version only.
- `removed`: on the previous version only.

Request: none

```json
{
  "detail": "Supplement changes retrieved successfully.",
  "data": [
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
}
```
