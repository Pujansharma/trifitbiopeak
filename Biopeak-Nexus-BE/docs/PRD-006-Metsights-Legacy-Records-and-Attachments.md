# PRD-006 — MetSights Legacy Records and Documents ePRD

The PWA can list a customer profile's Biopeak Health records, retrieve a selected record's documents with optional category, module, or file-role filters, and retrieve its consolidated report under Predictive Physiology.

Use `Authorization: Bearer <token>` with a Biopeak JWT for all requests. Customers can access only their own profiles and records. Administrators and associates can access existing profiles and records linked to those profiles.

## Logical Flow

1. **List profile records** — Request records for the selected profile and retain the selected item's `id` as `record_id`.
2. **List record documents** — Request attachments for that `record_id`, optionally passing category, module, or file-role filter codes.
3. **Get Predictive Physiology report** — When the user selects the separate hardcoded Predictive Physiology category, request the selected record's consolidated report.

## API Requests

### 1. List Profile Records

Returns the selected profile's available Biopeak Health records.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/metsights-legacy/records/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected Biopeak customer-profile UUID; must belong to the authenticated customer when using a customer JWT. |

#### Logic

Biopeak Health selection is fixed by the backend using `BIOPEAK_HEALTH`. No query filters are supported: `code`, `page`, `limit`, and `search` are ignored. The default first page contains up to 10 records, without `count`, `next`, or `previous` metadata.

Keep profile UUID in the request's cache identity. Use `data[].id` for the next request; the attachments URL does not contain the profile UUID.

#### Response — `200 OK`

```json
{
  "detail": "MetSights records fetched.",
  "data": [
    {
      "id": "<record_id>",
      "date": "2026-02-01",
      "has_physical_measurement": false,
      "has_vital_parameter": false,
      "has_blood_parameter": true,
      "has_diet_lifestyle_parameter": false,
      "has_fitness_parameter": false,
      "has_diet_preference_parameter": false,
      "has_food_frequency_diary_parameter": false,
      "has_collection": true,
      "has_blood_reports": true,
      "has_diagnostic_notes": false,
      "has_diet_plan": false,
      "has_estimated_parameter": false,
      "is_complete": true,
      "has_report": true,
      "has_pdf_report": true,
      "has_comprehensive_report": false,
      "is_report_shared": true,
      "has_personalised_plan": false,
      "completed_at": "2026-02-01T10:30:00+05:30",
      "created_at": "2026-02-01T09:00:00+05:30",
      "updated_at": "2026-02-01T10:30:00+05:30",
      "subscription": {
        "id": "<subscription_uuid>",
        "assessment": {
          "id": "<assessment_uuid>",
          "name": "Biopeak Health",
          "assessment_type": "Biopeak Health",
          "assessment_type_code": "12",
          "description": null
        }
      }
    }
  ]
}
```

`subscription` can be null. Assessment information is nested under `subscription.assessment`. The record does not return `subscription_id` or top-level `assessment_type`, `assessment_code`, `profile`, `demography`, or `config` fields.

An empty returned array is successful:

```json
{
  "detail": "MetSights records fetched.",
  "data": []
}
```

#### Errors

`404 Not Found` — the profile does not exist or is outside the authenticated customer's profiles:

```json
{
  "detail": "Customer profile with this ID not found."
}
```

`404 Not Found` — the profile has no linked MetSights profile, or the upstream records request returns an unsuccessful response or no data:

```json
{
  "detail": "MetSights records not found."
}
```

### 2. List Record Documents

The attachments endpoint is the document-list API for a selected legacy record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/attachments/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Exact `id` returned by List Profile Records; retain it as an opaque string. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category_type` | No | `imaging_body_analysis` | Exact named category code from the choices below. |
| `module_type` | No | `dxa_reports` | Exact named module code from the choices below. |
| `file_type` | No | `dxa_core_scan` | Exact file-role code from the choices below; this is not a filename extension or MIME type. |

**Filtered URL example:** `<baseURL>/profiles/metsights-legacy/records/:record_id/attachments/?category_type=imaging_body_analysis&module_type=dxa_reports&file_type=dxa_core_scan`

#### Logic

Omit the optional filters to request the default document list. The backend verifies that the record's remote profile is linked to an accessible Biopeak profile before retrieving its documents. A customer cannot access another customer's record by changing `record_id`.

Invalid filter values are ignored, as documented in the migration guide. Numeric category values such as `25`, `35`, and `45` are unsupported; use the named `category_type` codes below. `page`, `limit`, and `search` are ignored. The response contains up to 10 documents from the default first page without pagination metadata; `limit=1` does not restrict the result to one document.

Filters use codes, while response fields `metadata.category_type`, `metadata.module_type`, and `file_type` contain display labels. For example, send `category_type=imaging_body_analysis` and render `metadata.category_type` as `Imaging & Body Analysis`. Do not send the display label as the filter value. The response also provides the source label in `metadata.source` and its code in `metadata.source_code`.

Predictive Physiology is a separate hardcoded frontend category, outside these filter choices. Selecting it calls Get Predictive Physiology Report below; do not send it as `category_type`, `module_type`, or `file_type` to the attachments endpoint.

The local proxy forwards these three filters and passes through upstream document data. The upstream response fields, filter choices, invalid-filter behavior, and default page size below follow APIs 8–9 of [the PWA migration guide](biopeak-pwa-api-migration.md).

#### Supported Filter Choices

**`category_type`:**

| Code |
| --- |
| `unknown` |
| `clinical_lab_diagnostics` |
| `functional_metabolic_tests` |
| `genetics` |
| `imaging_body_analysis` |
| `psychophysiology_performance` |
| `consultation_notes` |
| `risk_landscape_rootcause` |

**`module_type`:** `physical_measurement`, `diet_lifestyle`, `body_vitals`, `blood_diagnostics`, `advanced_blood_diagnostics`, `gut_intelligence`, `fitness`, `health_lifestyle`, `clinician_notes`, `precision_blood_diagnostics`, `urine_metabolites`, `saliva_panel`, `dxa_reports`, `gut_microbiome`, `genetics_insights`, `breathing_stress`, `fitness_strength`, `ultrasonography`, `evo_imaging`, `consent_forms`, `oligoscans`, `steroid_hormones`, `somfit_panel`, `risk_landscape`, `genetics_nutri_dna`, `genetics_health_insights`.

**`file_type`:** `dxa_core_scan`, `dxa_body_composition`, `dxa_segmental_analysis`, `breathing_stress_profile_report`, `breathing_stress_respiratory_report`, `breathing_stress_communication_style`, `breathing_stress_cognifit`, `usg_carotid_doppler`, `usg_neck`, `usg_abdomen_pelvis`, `usg_arterial_doppler`, `usg_venous_doppler`, `usg_sonomammogram`, `usg_scrotum`, `usg_follicular_tvs`, `usg_pelvic_tvs`, `usg_others`, `genetics_functional`, `genetics_nutri_dna`, `genetics_health_insights`, `genetics_breast_ovarian_cancer`, `genetics_comprehensive`, `genetics_pharmacogenomics`, `genetics_inherited_cancer`, `genetics_nutri_dna_pdf`, `genetics_nutri_dna_vcf`, `genetics_health_insights_pdf`, `genetics_health_insights_vcf`, `bugspeaks_report_pdf`, `bugspeaks_additional_report_xls`, `steroid_hormone_profile`, `steroid_hormone_nad_longevity`, `steroid_hormone_nutri_toxic`, `steroid_hormone_fatty_acid`, `steroid_hormone_neurotransmitter_profile`, `fitness_strength_pelvic_floor`, `fitness_strength_physical_assessment`, `fitness_strength_vo2_max`.

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": [
    {
      "id": "<attachment_uuid>",
      "has_pii": false,
      "file": "<download_url>",
      "name": "report.pdf",
      "file_type": "Core Scan",
      "redacted_file": null,
      "attachment_date": "2026-02-01",
      "created_at": "2026-02-01T10:00:00+05:30",
      "updated_at": "2026-02-01T10:30:00+05:30",
      "metadata": {
        "id": "<metadata_uuid>",
        "module_type": "DXA Reports",
        "category_type": "Imaging & Body Analysis",
        "questionnaire_date": "2026-02-01",
        "assessment_date": "2026-02-01",
        "source": "Self",
        "source_code": "self",
        "practitioner_name": null,
        "consultation_type": "In person",
        "language": "English",
        "notes": null,
        "attachment": null,
        "files_count": 1,
        "created_at": "2026-02-01T09:00:00+05:30",
        "updated_at": "2026-02-01T10:30:00+05:30"
      }
    }
  ]
}
```

`name`, `file_type`, `redacted_file`, `attachment_date`, and optional metadata fields may be null. `questionnaire_date` and `assessment_date` represent the same assessment date.

An empty returned array, including when no documents match the selected filters, is successful:

```json
{
  "detail": "MetSights record resource fetched.",
  "data": []
}
```

#### Errors

`404 Not Found` — the record is unavailable, its remote profile is not linked to an accessible Biopeak profile, or the upstream documents request returns an unsuccessful response or no data:

```json
{
  "detail": "MetSights record resource not found."
}
```

### 3. Get Predictive Physiology Report

Returns the selected record's consolidated report file for the hardcoded **Predictive Physiology** category.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/report/consolidated/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Exact `id` returned by List Profile Records; the same record ownership checks apply. |

#### Logic

No query parameters are supported. Predictive Physiology is a frontend category label; it is not a filter code or a category field returned by this API. Display the consolidated report under that label and read its download URL from `data.file`.

The file response follows API 10 of the PWA migration guide. A null `data.file` means the report object exists without a stored file; handle it as an unavailable file within a successful response, separately from a `404`.

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": {
    "file": "<download_url>"
  }
}
```

When the report object exists without a stored file:

```json
{
  "detail": "MetSights record resource fetched.",
  "data": {
    "file": null
  }
}
```

#### Errors

`404 Not Found` — the record is unavailable, its remote profile is not linked to an accessible Biopeak profile, or the upstream consolidated report request returns an unsuccessful response or no data:

```json
{
  "detail": "MetSights record resource not found."
}
```
