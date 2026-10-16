# Document Category Frontend ePRD

Enables administrators to create and manage named document categories and map service document types to report/raw file
classifications.

All endpoints require an authenticated admin:

`Authorization: Bearer <token>`

No `X-Center-ID` header is required.

## Logical Flow

1. **List document categories** — Load the paginated category catalogue, optionally filtered by name.
2. **Create document category** — Create a category, optionally with its initial document-type assignments.
3. **Get category details** — Retrieve one category together with all current assignments.
4. **Update category** — Modify the category’s name, description, or active state.
5. **List assignments** — Load assignments independently when only the mapping collection is needed.
6. **Link assignments** — Add, replace, or remove document-type assignments atomically.
7. **Delete category** — Permanently delete the category and its assignments.

## API Requests

### Shared Assignment Values

Requests use document-type codes. Responses expose both the display label in `document_type` and the original code in
`document_type_code`.

| `document_type` code                       | Response label                  |
|--------------------------------------------|---------------------------------|
| `other`                                    | Other                           |
| `blood`                                    | Blood diagnostics Report        |
| `oligoscan`                                | OligoScan Report                |
| `somfit`                                   | SOMFIT Report                   |
| `metsights_pp`                             | MetSights Precision Plus Report |
| `evo_360`                                  | EVO 360 Report                  |
| `omics_urine`                              | Urine Metabolites Report        |
| `omics_cortisol`                           | Salivary Cortisol Report        |
| `dxa_core_scan`                            | Core Scan                       |
| `dxa_body_composition`                     | Body Composition                |
| `dxa_segmental_analysis`                   | Segmental Analysis              |
| `breathing_stress_profile_report`          | Stress Profile Report           |
| `breathing_stress_respiratory_report`      | Respiratory Report              |
| `breathing_stress_communication_style`     | Communication Style             |
| `breathing_stress_cognifit`                | Cognifit                        |
| `usg_carotid_doppler`                      | Bilateral Carotid Doppler       |
| `usg_neck`                                 | Neck & Thyroid                  |
| `usg_abdomen_pelvis`                       | Abdomen & Pelvis                |
| `usg_arterial_doppler`                     | Arterial Doppler                |
| `usg_venous_doppler`                       | Venous Doppler                  |
| `usg_sonomammogram`                        | Sonomammogram                   |
| `usg_scrotum`                              | Scrotum                         |
| `usg_follicular_tvs`                       | Follicular (TVS)                |
| `usg_pelvic_tvs`                           | Pelvic (TVS)                    |
| `usg_others`                               | Others (USG)                    |
| `genetics_functional`                      | Functional Genetics             |
| `genetics_nutri_dna`                       | NutriDNA                        |
| `genetics_health_insights`                 | Genomic Health Insights         |
| `genetics_breast_ovarian_cancer`           | Breast & Ovarian Cancer         |
| `genetics_comprehensive`                   | Comprehensive Genetics          |
| `genetics_pharmacogenomics`                | Pharmacogenomics                |
| `genetics_inherited_cancer`                | Inherited Cancer Genetics       |
| `genetics_nutri_dna_pdf`                   | NutriDNA PDF                    |
| `genetics_nutri_dna_vcf`                   | NutriDNA VCF                    |
| `bugspeaks_report`                         | Bugspeaks Report                |
| `steroid_hormone_profile`                  | Steroid Hormone Profile         |
| `steroid_hormone_nad_longevity`            | NAD+ Longevity Metabolism       |
| `steroid_hormone_nutri_toxic`              | Nutritional & Toxic Elements    |
| `steroid_hormone_fatty_acid`               | Fatty Acid (Omega 3) profile    |
| `steroid_hormone_neurotransmitter_profile` | Neurotransmitter profile        |
| `fitness_strength_pelvic_floor`            | Pelvic Floor Assessment         |
| `fitness_strength_physical_assessment`     | Physical Assessment             |
| `fitness_strength_vo2_max`                 | VO₂ max Report                  |

Allowed `document_categories` values:

| Code     | Meaning       |
|----------|---------------|
| `report` | Report file   |
| `raw`    | Raw data file |

Each assignment must contain one or two unique `document_categories`.

---

### 1. List Document Categories

Returns document categories ordered by newest first.

**Method:** `GET`

**URL:** `<baseURL>/products/document-categories/`

#### Query Parameters

| Name     | Required | Example    | Notes                                                                               |
|----------|----------|------------|-------------------------------------------------------------------------------------|
| `search` | No       | `genetics` | Case-insensitive category-name substring search; surrounding whitespace is removed. |
| `page`   | No       | `1`        | Page number; defaults to the first page.                                            |
| `limit`  | No       | `10`       | Page size; defaults to `10` and is capped at `50`.                                  |

There is no active-state filter. Both active and inactive categories can be returned.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01991f52-973e-7b72-906e-1b929d28881a",
      "name": "Genetics",
      "description": "Genetics-related reports and raw data.",
      "is_active": true,
      "created_at": "2026-09-18T10:30:00+05:30",
      "updated_at": "2026-09-18T10:30:00+05:30",
      "created_by": {
        "id": "01991f21-8ec4-7f88-b7ee-8ba982cb0041",
        "email": "admin@example.com",
        "first_name": "Platform",
        "last_name": "Admin",
        "image": null,
        "last_login": "2026-09-18T09:00:00+05:30"
      }
    }
  ]
}
```

---

### 2. Create Document Category

Creates a category and optionally creates its initial assignments in the same atomic operation.

**Method:** `POST`

**URL:** `<baseURL>/products/document-categories/`

#### Payload

| Name                        | Required                  | Example                       | Notes                                                                                      |
|-----------------------------|---------------------------|-------------------------------|--------------------------------------------------------------------------------------------|
| `name`                      | Yes                       | `Genetics`                    | Non-blank category name.                                                                   |
| `description`               | No                        | `Genetics-related documents.` | May be a string, an empty string, or `null`.                                               |
| `is_active`                 | No                        | `true`                        | Defaults to `true`.                                                                        |
| `add`                       | No                        | See example                   | Array of initial assignments; may be omitted or empty.                                     |
| `add[].document_type`       | When an `add` item exists | `genetics_nutri_dna`          | Must be one of the documented document-type codes. Each code may occur only once in `add`. |
| `add[].document_categories` | When an `add` item exists | `["report", "raw"]`           | Non-empty array containing one or two unique values: `report` and/or `raw`.                |

```json
{
  "name": "Genetics",
  "description": "Genetics-related reports and raw data.",
  "is_active": true,
  "add": [
    {
      "document_type": "genetics_nutri_dna",
      "document_categories": [
        "report",
        "raw"
      ]
    }
  ]
}
```

#### Logic

The category and all initial assignments are created atomically. The success response does not contain the created
assignments; retrieve the category detail or assignment list when they are needed.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01991f52-973e-7b72-906e-1b929d28881a",
    "name": "Genetics",
    "description": "Genetics-related reports and raw data.",
    "is_active": true,
    "created_at": "2026-09-18T10:30:00+05:30",
    "updated_at": "2026-09-18T10:30:00+05:30",
    "created_by": {
      "id": "01991f21-8ec4-7f88-b7ee-8ba982cb0041",
      "email": "admin@example.com",
      "first_name": "Platform",
      "last_name": "Admin",
      "image": null,
      "last_login": "2026-09-18T09:00:00+05:30"
    }
  }
}
```

#### Errors

Missing category name — `400 Bad Request`:

```json
{
  "detail": {
    "name": [
      "This field is required."
    ]
  }
}
```

Repeated document type in `add` — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      "Duplicate document_type entries are not allowed."
    ]
  }
}
```

Repeated document category — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      {
        "document_categories": [
          "document_categories must not contain duplicate values."
        ]
      }
    ]
  }
}
```

More than two document categories — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      {
        "document_categories": [
          "document_categories may contain at most 2 values."
        ]
      }
    ]
  }
}
```

Invalid document type — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      {
        "document_type": [
          "\"unsupported\" is not a valid choice."
        ]
      }
    ]
  }
}
```

---

### 3. Get Document Category Details

Returns one category and all its assignments.

**Method:** `GET`

**URL:** `<baseURL>/products/document-categories/<pk>/`

#### Path Parameters

| Name | Required | Example                                | Notes                   |
|------|----------|----------------------------------------|-------------------------|
| `pk` | Yes      | `01991f52-973e-7b72-906e-1b929d28881a` | Document category UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "01991f52-973e-7b72-906e-1b929d28881a",
    "name": "Genetics",
    "description": "Genetics-related reports and raw data.",
    "assignments": [
      {
        "id": "01991f58-308a-7cf8-9b49-fcd802559ccd",
        "document_type": "NutriDNA",
        "document_type_code": "genetics_nutri_dna",
        "document_categories": [
          "report",
          "raw"
        ],
        "created_at": "2026-09-18T10:30:00+05:30",
        "updated_at": "2026-09-18T10:30:00+05:30"
      }
    ],
    "is_active": true,
    "created_at": "2026-09-18T10:30:00+05:30",
    "updated_at": "2026-09-18T10:30:00+05:30",
    "created_by": {
      "id": "01991f21-8ec4-7f88-b7ee-8ba982cb0041",
      "email": "admin@example.com",
      "first_name": "Platform",
      "last_name": "Admin",
      "image": null,
      "last_login": "2026-09-18T09:00:00+05:30"
    }
  }
}
```

#### Errors

Category not found — `404 Not Found`:

```json
{
  "detail": "No DocumentCategory matches the given query."
}
```

---

### 4. Update Document Category

Partially updates the category. Assignments cannot be changed through this endpoint.

**Method:** `PATCH`

**URL:** `<baseURL>/products/document-categories/<pk>/`

#### Path Parameters

| Name | Required | Example                                | Notes                   |
|------|----------|----------------------------------------|-------------------------|
| `pk` | Yes      | `01991f52-973e-7b72-906e-1b929d28881a` | Document category UUID. |

#### Payload

| Name          | Required | Example                       | Notes                                        |
|---------------|----------|-------------------------------|----------------------------------------------|
| `name`        | No       | `Genetic Assessments`         | Must be non-blank when provided.             |
| `description` | No       | `Genetic assessment outputs.` | May be a string, an empty string, or `null`. |
| `is_active`   | No       | `false`                       | Controls whether the category is active.     |

```json
{
  "name": "Genetic Assessments",
  "description": "Genetic assessment outputs.",
  "is_active": false
}
```

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "01991f52-973e-7b72-906e-1b929d28881a",
    "name": "Genetic Assessments",
    "description": "Genetic assessment outputs.",
    "assignments": [
      {
        "id": "01991f58-308a-7cf8-9b49-fcd802559ccd",
        "document_type": "NutriDNA",
        "document_type_code": "genetics_nutri_dna",
        "document_categories": [
          "report",
          "raw"
        ],
        "created_at": "2026-09-18T10:30:00+05:30",
        "updated_at": "2026-09-18T10:30:00+05:30"
      }
    ],
    "is_active": false,
    "created_at": "2026-09-18T10:30:00+05:30",
    "updated_at": "2026-09-18T11:15:00+05:30",
    "created_by": {
      "id": "01991f21-8ec4-7f88-b7ee-8ba982cb0041",
      "email": "admin@example.com",
      "first_name": "Platform",
      "last_name": "Admin",
      "image": null,
      "last_login": "2026-09-18T09:00:00+05:30"
    }
  }
}
```

#### Errors

Blank name — `400 Bad Request`:

```json
{
  "detail": {
    "name": [
      "This field may not be blank."
    ]
  }
}
```

Category not found — `404 Not Found`:

```json
{
  "detail": "No DocumentCategory matches the given query."
}
```

---

### 5. List Document Category Assignments

Returns the paginated assignments belonging to the supplied category UUID.

**Method:** `GET`

**URL:** `<baseURL>/products/document-categories/<pk>/assignments/`

#### Path Parameters

| Name | Required | Example                                | Notes                   |
|------|----------|----------------------------------------|-------------------------|
| `pk` | Yes      | `01991f52-973e-7b72-906e-1b929d28881a` | Document category UUID. |

#### Query Parameters

| Name    | Required | Example | Notes                                              |
|---------|----------|---------|----------------------------------------------------|
| `page`  | No       | `1`     | Page number; defaults to the first page.           |
| `limit` | No       | `10`    | Page size; defaults to `10` and is capped at `50`. |

#### Logic

This endpoint filters assignments by the supplied UUID but does not verify that the parent category exists. A valid but
nonexistent category UUID therefore returns an empty successful list.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01991f58-308a-7cf8-9b49-fcd802559ccd",
      "document_type": "NutriDNA",
      "document_type_code": "genetics_nutri_dna",
      "document_categories": [
        "report",
        "raw"
      ],
      "created_at": "2026-09-18T10:30:00+05:30",
      "updated_at": "2026-09-18T10:30:00+05:30"
    }
  ]
}
```

For a valid but nonexistent category UUID:

```json
{
  "detail": "All data.",
  "count": 0,
  "next": null,
  "previous": null,
  "data": []
}
```

---

### 6. Link Document Category Assignments

Atomically adds, replaces, and/or removes assignments for one category.

**Method:** `POST`

**URL:** `<baseURL>/products/document-categories/<pk>/link-assignments/`

#### Path Parameters

| Name | Required | Example                                | Notes                            |
|------|----------|----------------------------------------|----------------------------------|
| `pk` | Yes      | `01991f52-973e-7b72-906e-1b929d28881a` | Existing document category UUID. |

#### Payload

| Name                        | Required                    | Example                  | Notes                                                        |
|-----------------------------|-----------------------------|--------------------------|--------------------------------------------------------------|
| `add`                       | Conditional                 | See example              | At least one of `add` or `remove` must be a non-empty array. |
| `add[].document_type`       | When an `add` item exists   | `genetics_nutri_dna`     | Must be unique within `add`.                                 |
| `add[].document_categories` | When an `add` item exists   | `["report"]`             | One or two unique values: `report` and/or `raw`.             |
| `remove`                    | Conditional                 | See example              | At least one of `add` or `remove` must be a non-empty array. |
| `remove[].document_type`    | When a `remove` item exists | `genetics_nutri_dna_vcf` | Identifies the entire assignment to delete.                  |

```json
{
  "add": [
    {
      "document_type": "genetics_nutri_dna",
      "document_categories": [
        "report"
      ]
    },
    {
      "document_type": "genetics_health_insights",
      "document_categories": [
        "report",
        "raw"
      ]
    }
  ],
  "remove": [
    {
      "document_type": "genetics_nutri_dna_vcf"
    }
  ]
}
```

#### Logic

- Removals run before additions within one database transaction.
- Adding a document type that already exists replaces its entire `document_categories` array; values are not merged.
- Removing a document type deletes its complete assignment.
- If the same document type appears in both `remove` and `add`, the final state contains the newly added assignment.
- The response contains an empty `data` object because all serializer fields are write-only. Refetch the detail or
  assignment list to obtain the updated mappings.

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {}
}
```

#### Errors

Neither operation supplied, or both arrays are empty — `400 Bad Request`:

```json
{
  "detail": "At least one of 'add' or 'remove' must be provided."
}
```

Repeated document type in `add` — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      "Duplicate document_type entries are not allowed."
    ]
  }
}
```

Repeated category within an assignment — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      {
        "document_categories": [
          "document_categories must not contain duplicate values."
        ]
      }
    ]
  }
}
```

More than two categories within an assignment — `400 Bad Request`:

```json
{
  "detail": {
    "add": [
      {
        "document_categories": [
          "document_categories may contain at most 2 values."
        ]
      }
    ]
  }
}
```

Category not found — `404 Not Found`:

```json
{
  "detail": "Document category not found."
}
```

---

### 7. Delete Document Category

Permanently deletes the category. Its linked assignments are deleted through the category relationship’s cascade
behavior.

**Method:** `DELETE`

**URL:** `<baseURL>/products/document-categories/<pk>/`

#### Path Parameters

| Name | Required | Example                                | Notes                   |
|------|----------|----------------------------------------|-------------------------|
| `pk` | Yes      | `01991f52-973e-7b72-906e-1b929d28881a` | Document category UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Deleted successfully."
}
```

#### Errors

Category not found — `404 Not Found`:

```json
{
  "detail": "No DocumentCategory matches the given query."
}
```
