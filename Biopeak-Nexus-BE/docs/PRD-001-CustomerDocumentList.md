# PRD-001 — Customer Document List ePRD

The frontend can list every document belonging to a customer profile and optionally filter the list through a saved document-category definition.

## Logical Flow

1. **List customer documents** — Request the profile's paginated document list and send `document_category_id` when the user selects a saved document category.

## API Requests

### 1. List Customer Documents

Returns documents belonging to the selected customer profile, with optional exact, module, date, search, activity, and saved-category filters.

**Method:** `GET`

**URL:** `<baseURL>/profiles/<customer_profile_id>/documents/`

Use `Authorization: Bearer <token>`. Administrators and associates can request any existing profile. Customers can request only profiles belonging to their own customer account.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `customer_profile_id` | Yes | `019e2117-5baf-71bc-ad9e-5619f1dc8dba` | Customer-profile UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `blood` | Case-insensitive match against filename, provider name, product name, or assigned service name. |
| `active` | No | `1` | `0` returns inactive documents and `1` returns active documents; omission returns both. |
| `document_type` | No | `oligoscan` | Exact parent-result document-type code. |
| `document_category` | No | `raw` | Exact file category: `report` or `raw`. |
| `document_category_id` | No | `01991f52-973e-7b72-906e-1b929d28881a` | UUID of a saved `DocumentCategory`; omission applies no saved-category filter. |
| `module_category` | No | `functional_metabolic_tests` | Module-category code; an unknown code returns an empty list. |
| `date_from` | No | `2026-08-01` | Inclusive lower bound for the parent result's sample-collection date. |
| `date_to` | No | `2026-08-17` | Inclusive upper bound for the parent result's sample-collection date and must not precede `date_from`. |
| `page` | No | `1` | Page number; defaults to the first page. |
| `limit` | No | `10` | Page size; defaults to `10` and is capped at `50`. |

#### Logic

Each saved-category assignment is evaluated as one paired condition:

```text
(result.document_type = assignment.document_type
 AND document.document_category IN assignment.document_categories)
```

Multiple assignments are joined with `OR`. Profile scope and every other supplied query filter are then combined with that assignment group using `AND`. This preserves each assignment's type/category pairing and prevents cross-matches between different assignments.

A malformed, blank, nonexistent, or unassigned `document_category_id` returns a successful empty paginated list. It is not treated as an error and is never ignored. The backend does not require a separate document-category existence request before listing documents.

Supported `module_category` codes are `unknown`, `clinical_lab_diagnostics`, `functional_metabolic_tests`, `genetics`, `imaging_body_analysis`, `psychophysiology_performance`, `consultation_notes`, and `risk_landscape_rootcause`.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f73bd-0616-7aa4-b099-9faeedc9cff1",
      "result": {
        "id": "019f73ba-b86f-7f94-a806-ddb939bc33d1",
        "program_service": {
          "id": "019f73b6-5e0d-75cb-a3bc-483c718ec13a",
          "service": {
            "id": "019f5162-217e-732e-b8ae-755ca13ae346",
            "name": "OligoScan",
            "service_category": "Assessment",
            "service_category_code": "assessment",
            "image": null
          },
          "composite_program": {
            "id": "019f73b2-cc61-7c34-b24a-d9d9b15611e3",
            "uid": "P0001",
            "name": "Longevity Program"
          },
          "composite_template": {
            "id": "019f739f-e190-7821-a3e6-924b7b126a6c",
            "code": "LONGEVITY-01",
            "name": "Longevity Template",
            "is_active": true
          }
        },
        "product": {
          "id": "019f73a9-a307-755d-a955-a4f515d30bcd",
          "name": "OligoScan Test",
          "code": "OLIGO-001"
        },
        "provider_name": "OligoScan",
        "product_name": "OligoScan Test",
        "result_mode": "Upload",
        "result_mode_code": "upload",
        "document_type": "OligoScan Report",
        "document_type_code": "oligoscan",
        "documents_count": 1,
        "sample_collection_date": "2026-08-10",
        "report_generation_date": "2026-08-12"
      },
      "file": "<file_url>",
      "filename": "oligoscan-raw.json",
      "content_type": "application/json",
      "document_category": "Raw data file",
      "document_category_code": "raw",
      "module_category": "Functional & Metabolic Tests",
      "module_category_code": "functional_metabolic_tests",
      "is_active": true,
      "created_at": "2026-08-12T10:30:00+05:30",
      "updated_at": "2026-08-12T10:30:00+05:30"
    }
  ]
}
```

`result.product`, `result.provider_name`, `result.product_name`, `result.program_service.composite_program`, and `result.program_service.composite_template` can be `null`.

When no records match, the same endpoint returns:

```json
{
  "detail": "All data.",
  "count": 0,
  "next": null,
  "previous": null,
  "data": []
}
```

#### Errors

`400 Bad Request` — `date_to` precedes `date_from`:

```json
{
  "detail": "Date to must be on or after date from."
}
```

`404 Not Found` — the profile does not exist or does not belong to the authenticated customer:

```json
{
  "detail": "Customer profile with this ID not found."
}
```
