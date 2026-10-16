# AI Integration API Migration — ePRD

Replace the AI integration's MetSights reads with Biopeak profile, care-team, assessment-service, document, and ID-mapping APIs.

| Objective | Old API | New URLs |
| --- | --- | --- |
| List patient profiles | New external operation | `https://api.biopeak.com/external/customer-profiles/` |
| Read patient details | `https://api.metsights.com/profiles/:client_id/` | `https://api.biopeak.com/profiles/:profile_id/` |
| Read linked specialists | `https://api.metsights.com/profiles/:client_id/specialists/` | `https://api.biopeak.com/profiles/:profile_id/associates/` |
| Discover assessments | `https://api.metsights.com/profiles/:client_id/records/` | `https://api.biopeak.com/profiles/:profile_id/program-services/?type=assessment` |
| Read patient documents | `https://api.metsights.com/records/:record_id/attachments/` | `https://api.biopeak.com/profiles/:profile_id/documents/` |
| Map MetSights and Biopeak profile IDs | No existing URL supplied; new operation | `https://api.biopeak.com/profiles/:profile_id/metsights-profile/` |

## X-API-KEY authentication — all six APIs

Send the raw service-account key as `X-API-KEY: <service-account key>` on every GET request below, including requests to pagination `next` URLs. API-key requests do not require an `Authorization` header, customer JWT, `X-Center-ID`, or `X-Customer-Profile-ID`. For profile-specific URLs, pass the Biopeak customer-profile UUID in the path.

Service accounts are managed exclusively through Django admin: the generated key is displayed once, only its SHA-256 hash is stored, and inactive or expired accounts are rejected. API-key access can list profiles across customers and read any specified profile through the APIs below; it grants no write-method access. The mapping GET may create the mapping as described in API 6. Customer JWT reads retain ownership filtering. Existing staff JWT access remains available on the profile-specific operations; profile detail, program services, and mapping retain staff center restrictions using `X-Center-ID` or `center_id`.

`GET /profiles/` remains customer-only and lists the authenticated customer's profiles. It does not support API-key access and is excluded from this AI integration flow.

**Shared authentication error — `403 Forbidden`**

For requests using API-key access without a JWT, missing, invalid, inactive, or expired credentials return:

```json
{"detail": "API key is either missing, invalid, or expired."}
```

List responses use `data`, `count`, `next`, and `previous`, with `detail: "All data."`. Follow `next` as a complete URL; there is no `next_page`. Default page size is 10; `limit` is capped at 50. Single-object responses use `{ "detail": "Details.", "data": { ... } }`. These views do not add a `success` property.

## Logical Flow

1. **List customer profiles** — Discover Biopeak profile UUIDs through the new external endpoint.
2. **Read profile** — Load patient identity and demographic details using the selected Biopeak profile UUID.
3. **List associates** — Load the patient's linked care team.
4. **List program services** — Discover assessment services across the patient's programs.
5. **List documents** — Read the patient's report files with supported search and filters.
6. **Read MetSights mapping** — Resolve the MetSights profile ID when the integration needs both systems' identifiers.

## API Requests

### 1. List customer profiles

The new external endpoint returns profiles across customers using an independent `ExternalCustomerProfileSerializer` with the same item shape as the customer-profile response. Only API-key access is accepted; a customer or staff JWT alone does not authorize this endpoint.

**Method:** `GET`

**URL:** `https://api.biopeak.com/external/customer-profiles/`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `active` | No | `1` | `1` selects active profiles; `0` selects inactive profiles. Omission or another value leaves activity unfiltered. |
| `page` | No | `1` | Default 1 |
| `limit` | No | `10` | Default 10; maximum 50 |

**Response — `200 OK`**

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019a5bf0-5ec0-7000-8000-000000000001",
      "email": "patient@example.com",
      "phone": "+919876543210",
      "first_name": "Mukul",
      "last_name": "Gulati",
      "gender": "Male",
      "date_of_birth": "1990-06-15",
      "age": 36,
      "image": null,
      "is_main": true,
      "is_onboarding_sent": true,
      "is_onboarding_completed": true,
      "created_at": "2026-10-08T10:00:00+05:30",
      "updated_at": "2026-10-08T10:00:00+05:30"
    }
  ]
}
```

Profiles sort by descending creation time, then descending profile UUID. There is no customer or center restriction and no search parameter. `email` and `phone` come from the customer account; family profiles share those account contacts. `gender` is the display label, and `age` is `null` for missing or future birth dates. An empty result returns the same pagination wrapper with `count: 0`, `next: null`, `previous: null`, and `data: []`. Authentication failures use the shared `403` response above.

### 2. Read profile

`CustomerProfileDetailView` returns the same `CustomerProfileSerializer` shape for one Biopeak profile.

**Method:** `GET`

**URL:** `https://api.biopeak.com/profiles/:profile_id/`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019a5bf0-5ec0-7000-8000-000000000001` | Biopeak CustomerProfile UUID; path parameter |
| `center_id` | Staff JWT only, unless header supplied | `<center UUID>` | Query alternative to `X-Center-ID`; the header takes precedence. API-key and customer callers do not need it. |

**Response — `200 OK`**

```json
{
  "detail": "Details.",
  "data": {
    "id": "019a5bf0-5ec0-7000-8000-000000000001",
    "email": "patient@example.com",
    "phone": "+919876543210",
    "first_name": "Mukul",
    "last_name": "Gulati",
    "gender": "Male",
    "date_of_birth": "1990-06-15",
    "age": 36,
    "image": null,
    "is_main": true,
    "is_onboarding_sent": true,
    "is_onboarding_completed": true,
    "created_at": "2026-10-07T10:00:00+05:30",
    "updated_at": "2026-10-07T10:00:00+05:30"
  }
}
```

**Error — `404 Not Found`**

```json
{"detail": "Customer profile not found."}
```

### 3. List associates

`CustomerAssociateListView` returns linked associate assignments using `CustomerAssociateSerializer`.

**Method:** `GET`

**URL:** `https://api.biopeak.com/profiles/:profile_id/associates/`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019a5bf0-5ec0-7000-8000-000000000001` | Biopeak CustomerProfile UUID; path parameter |
| `center_id` | No | `<center UUID>` | Repeat to select multiple centers. A resolved `X-Center-ID` overrides the query values. |
| `role_id` | No | `<associate-role UUID>` | Matches an active role on an active center assignment. |
| `search` | No | `Mukul` | Trimmed, case-insensitive prefix match on associate full name or email. |
| `page` | No | `1` | Default 1 |
| `limit` | No | `10` | Default 10; maximum 50 |

**Response — `200 OK`**

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019a5bf0-5ec0-7000-8000-000000000002",
      "email": "doctor@example.com",
      "phone": "+919876543211",
      "first_name": "Anita",
      "last_name": "Rao",
      "gender": "Female",
      "date_of_birth": "1985-04-20",
      "image": null,
      "is_active": true,
      "created_at": "2026-10-07T10:00:00+05:30",
      "roles": [
        {
          "id": "019a5bf0-5ec0-7000-8000-000000000003",
          "name": "Doctor",
          "role_tag": "doctor",
          "is_system": false,
          "is_active": true,
          "created_at": "2026-10-07T10:00:00+05:30",
          "updated_at": "2026-10-07T10:00:00+05:30"
        }
      ],
      "role_ids": ["019a5bf0-5ec0-7000-8000-000000000003"],
      "created_by": null,
      "contact_phone": null,
      "title": null,
      "description": "Consulting physician",
      "tagline": "Preventive care",
      "experience": 12.0,
      "qualifications": ["MBBS"],
      "professions": ["Physician"],
      "has_verified_badge": true
    }
  ]
}
```

Items sort newest assignment first. `id` is the associate's user UUID. More than one assignment can refer to the same associate across centers. Roles come from that associate's center assignment. `created_by`, when present, contains `id`, `email`, `first_name`, `last_name`, `image`, and `last_login`. The view preserves associate JWT center filtering and customer ownership checks.

### 4. List program services

`CustomerProgramServicesView` returns `AssessmentProgramServiceSerializer` items across all program types.

**Method:** `GET`

**URL:** `https://api.biopeak.com/profiles/:profile_id/program-services/?type=assessment`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019a5bf0-5ec0-7000-8000-000000000001` | Biopeak CustomerProfile UUID; path parameter |
| `type` | No | `assessment` | Service category: `assessment`, `therapy`, or `consultation`. Omission returns all three. It does not filter the parent program type. |
| `center_id` | Staff JWT only, unless header supplied | `<center UUID>` | Header alternative; staff reads retain profile assignment and program center/redeemable-center restrictions. |
| `page` | No | `1` | Default 1 |
| `limit` | No | `10` | Default 10; maximum 50 |

**Response — `200 OK`**

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019a5bf0-5ec0-7000-8000-000000000004",
      "service": {
        "id": "019a5bf0-5ec0-7000-8000-000000000005",
        "name": "Blood Diagnostics",
        "service_category": "Assessment",
        "service_category_code": "assessment",
        "image": null,
        "centers": null
      },
      "data": {},
      "assignment_type": "Standalone",
      "assignment_type_code": "standalone",
      "results_count": 1,
      "documents_count": 1,
      "reports_count": 1,
      "raw_data_count": 0,
      "fetch_count": 1,
      "fetch_results_count": 1,
      "fetch_documents_count": 1,
      "fetch_pending_count": 0,
      "created_date": "2026-10-07",
      "created_by": null,
      "is_active": true,
      "created_at": "2026-10-07T10:00:00+05:30",
      "updated_at": "2026-10-07T10:00:00+05:30",
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null
    }
  ]
}
```

This replaces assessment discovery; a separate records API is unnecessary. Items are ProgramServices, and their IDs are Biopeak service-assignment IDs rather than MetSights record IDs. `created_date` is assignment creation date, not an assessment date. There is no top-level `date` field or nested list of records. Inactive assignments remain eligible; items sort newest first. User objects use the shape noted for associates. `service.centers` is `null` when there are no active assignments, otherwise a preview of up to three centers.

**Error — `400 Bad Request`**

```json
{"detail": "Invalid type. Use assessment, therapy, or consultation."}
```

**Error — `404 Not Found`**

```json
{"detail": "Customer profile not found."}
```

### 5. List documents

`CustomerProfileDocumentsListView` returns active files using `CustomerServiceDocumentSerializer`, with their results and program-service context nested in each item.

**Method:** `GET`

**URL:** `https://api.biopeak.com/profiles/:profile_id/documents/`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019a5bf0-5ec0-7000-8000-000000000001` | Biopeak CustomerProfile UUID; path parameter |
| `search` | No | `blood` | Trimmed, case-insensitive substring match on result provider name, product name, or service name; does not search filenames. |
| `year` | No | `2026` | Sample-collection year, 1–9999; invalid values are ignored. Leading zeros are removed. |
| `month` | No | `10` | Sample-collection month, 1–12; applied only alongside a valid `year`. Invalid values are ignored. |
| `document_type` | No | `blood` | Exact result document-type code, for example `blood`, `bugspeaks_report`, `genetics_nutri_dna`, or `metsights_pp`. |
| `document_category` | No | `report` | Exact document category: `report` or `raw`. |
| `document_category_id` | No | `<document-category UUID>` | Matches the category's configured document-type/category combinations; unknown or unconfigured IDs produce no items. |
| `module_category` | No | `clinical_lab_diagnostics` | Maps to result document types; unknown codes produce no items. |
| `report_component` | No | `metsights-consolidated` | Valid component codes listed below; invalid values are ignored. |
| `date_from` | No | `2026-10-01` | Inclusive lower bound on sample-collection date; use `YYYY-MM-DD`. |
| `date_to` | No | `2026-10-31` | Inclusive upper bound on sample-collection date; use `YYYY-MM-DD`. |
| `page` | No | `1` | Default 1 |
| `limit` | No | `10` | Default 10; maximum 50 |

Module-category codes are `unknown`, `clinical_lab_diagnostics`, `functional_metabolic_tests`, `genetics`, `imaging_body_analysis`, `psychophysiology_performance`, `consultation_notes`, and `risk_landscape_rootcause`. Report-component codes are `metsights-health-risk-landscape`, `metsights-lifestyle-blueprint`, `metsights-supplement-blueprint`, and `metsights-consolidated`. Supplied filters combine; documents sort newest first. Category-ID mappings internally match any configured document-type/category combination.

**Response — `200 OK`**

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019a5bf0-5ec0-7000-8000-000000000006",
      "result": {
        "id": "019a5bf0-5ec0-7000-8000-000000000007",
        "program_service": {
          "id": "019a5bf0-5ec0-7000-8000-000000000004",
          "service": {
            "id": "019a5bf0-5ec0-7000-8000-000000000005",
            "name": "Blood Diagnostics",
            "service_category": "Assessment",
            "service_category_code": "assessment",
            "image": null,
            "centers": null
          },
          "program": {
            "id": "019a5bf0-5ec0-7000-8000-000000000008",
            "uid": null,
            "program_type": "Assessment Program",
            "program_type_code": "assessment"
          },
          "composite_program": null,
          "composite_template": null
        },
        "product": {
          "id": "019a5bf0-5ec0-7000-8000-000000000009",
          "name": "Blood Panel",
          "code": "PC-0001"
        },
        "provider_name": "Diagnostic Provider",
        "product_name": "Blood Panel",
        "result_mode": "Fetch",
        "result_mode_code": "fetch",
        "document_type": "Blood diagnostics Report",
        "document_type_code": "blood",
        "documents_count": 1,
        "sample_collection_date": "2026-10-07",
        "report_generation_date": "2026-10-08"
      },
      "file": "https://files.biopeak.com/reports/blood-panel.pdf",
      "filename": "blood-panel.pdf",
      "content_type": "application/pdf",
      "document_category": "Report file",
      "document_category_code": "report",
      "report_component": null,
      "report_component_code": null,
      "module_category": "Clinical Lab Diagnostics",
      "module_category_code": "clinical_lab_diagnostics",
      "is_active": true,
      "created_at": "2026-10-08T10:00:00+05:30",
      "updated_at": "2026-10-08T10:00:00+05:30"
    }
  ]
}
```

The file URL is illustrative; use the URL returned by storage. This endpoint lists documents directly for a profile, so no MetSights `record_id` is needed. Use `filename` in place of `name`, and `content_type` in place of `file_type`. `has_pii` and the old `metadata` object are absent. Module/category codes are on the document; assessment collection date is `result.sample_collection_date`. Labels and their `_code` fields are distinct. `product` and result dates may be `null`. Composite context is populated for composite programs; these fields remain `null` for standalone programs.

### 6. Read MetSights mapping

`CustomerMetsightsProfileView` returns the existing mapping model using the read-only `CustomerMetsightsProfileSerializer`.

**Method:** `GET`

**URL:** `https://api.biopeak.com/profiles/:profile_id/metsights-profile/`

**Required header:** `X-API-KEY: <service-account key>`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019a5bf0-5ec0-7000-8000-000000000001` | Biopeak CustomerProfile UUID; path parameter |
| `center_id` | Staff JWT only, unless header supplied | `<center UUID>` | Query alternative to `X-Center-ID`; API-key and customer callers do not need it. |

**Response — `200 OK`**

```json
{
  "detail": "Details.",
  "data": {
    "profile_id": "MS-1042",
    "is_active": true,
    "created_at": "2026-10-08T10:00:00+05:30",
    "updated_at": "2026-10-08T10:00:00+05:30"
  }
}
```

The URL identifies the Biopeak profile; the response's `profile_id` is the MetSights ID. The response does not repeat `customer_profile`. An existing populated mapping returns immediately. When the mapping is missing or its ID is empty, the helper finds or creates the remote profile, stores its ID, and returns the mapping. This GET can therefore create a mapping. A failed lookup or unavailable remote ID returns 503 and preserves existing mapping data.

**Error — `503 Service Unavailable`**

```json
{"detail": "MetSights profile mapping is unavailable."}
```

**Error — `404 Not Found`**

```json
{"detail": "Customer profile not found."}
```
