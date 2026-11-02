# Program Service Responsibilities — Frontend ePRD

Implement assigned therapy, assessment, and consultation screens with category-specific actions.

This numbered ePRD groups the assigned-service workflows by category. Existing assessment result, request, and
file-deletion URLs remain supported; their category URLs are additive aliases. Consultation document detail URLs
remain available for GET and DELETE. Consultation uploads now create a document with its file in one request;
file-only routes and document PATCH/PUT have been removed. Clients using those consultation operations must update.

Use `Authorization: Bearer <token>`. All paths below identify assigned program services or their owned records;
catalogue service IDs belong to `/services/` and must not replace assigned IDs.

| Responsibility            | Therapy | Assessment                               | Consultation                                   |
|---------------------------|---------|------------------------------------------|------------------------------------------------|
| Assigned center alignment | Yes     | No                                       | No                                             |
| Result/file uploads       | None    | Assessment result, then report/raw files | One document containing one uploaded file      |
| Cancellation              | Yes     | Yes                                      | Yes; existing route retained                   |

Catalogue center coverage is unchanged. For assessment and consultation, the existing nested `service.centers` field
remains a catalogue preview or null; it does not represent assigned-center links. Parent-program owning/redeemable
centers still control applicable access. Therapy's selected centers are described in its mini ePRD below.

Creator fields may be null on historical records. Cancellation audit fields remain null until cancellation; file and
image values may be URLs or null where the underlying field permits it.

## Therapy mini ePRD

### Logical Flow

1. **Read the assigned therapy service** — Load the service identity, sessions, and selected centers.
2. **Add therapy sessions** — Add a positive session increment or update parent-program credit/complimentary flags through an active service in an active, unexpired program.
3. **List assigned therapy centers** — Read all selected centers and their parent-program membership.
4. **List available therapy centers** — Discover the parent program's redeemable centers and identify service selections and the customer profile's home center.
5. **Add therapy centers** — Append selected centers without replacing existing assignments.
6. **Cancel the therapy service** — Cancel remaining therapy allowance with an audit reason and date.

### API Requests

#### 1. Read the assigned therapy service

Load the service identity, sessions, and selected centers.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<program_service_uuid>",
    "program": {
      "id": "<program_uuid>",
      "uid": "P0001",
      "profile": {
        "id": "<profile_uuid>",
        "contact_email": "client@example.com",
        "phone": "+919876543210",
        "first_name": "Ravi",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-04-12",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": false,
        "created_at": "2026-10-24T10:00:00+05:30",
        "updated_at": "2026-10-24T10:00:00+05:30"
      },
      "program_type": "Therapy Program",
      "notes": null,
      "expires_at": "2026-12-31",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 1,
      "sessions_count": 6,
      "sessions_used": 1,
      "sessions_cancelled": 0,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "created_date": "2026-10-24",
      "cancelled_date": null,
      "is_active": true,
      "created_at": "2026-10-24T10:00:00+05:30",
      "updated_at": "2026-10-24T10:00:00+05:30"
    },
    "redeemable_centers": [
      {
        "id": "<center_uuid>",
        "code": "C0001",
        "name": "Bengaluru"
      }
    ],
    "service": {
      "id": "<catalogue_service_uuid>",
      "name": "Recovery Therapy",
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "centers": [
        {
          "id": "<center_uuid>",
          "code": "C0001",
          "name": "Bengaluru"
        }
      ]
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "sessions_count": 6,
    "sessions_used": 1,
    "sessions_cancelled": 0,
    "redeem_code": "ABCD123456",
    "created_date": "2026-10-24",
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

##### Logic

Admins and associates may read. Customers may read only services belonging to their own customer account. The ID is the
assigned service ID, not the catalogue ID. Therapy has no result/file-upload operation. Center arrays are selected
therapy-service centers; use the dedicated center list for membership flags.

#### 2. Add therapy sessions

Increase the assigned therapy service's allowance and optionally update its parent program's classification flags.

**Method:** `PATCH`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `019fb7e9-12aa-7261-9f30-a41766a24bc1` | Assigned ProgramService UUID, not the catalogue service ID. |

##### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `sessions_count` | No | `12` | Positive integer increment. Omission leaves the allowance unchanged. Zero, negative, null, and fractional values are rejected by the field. |
| `is_complimentary` | No | `true` | Top-level boolean updating the parent Program. Omission retains its stored value. |
| `is_credit` | No | `false` | Top-level boolean updating the parent Program. Omission retains its stored value. |

```json
{
  "sessions_count": 12,
  "is_complimentary": true,
  "is_credit": false
}
```

##### Logic

Admins and any associates may update; no program-center assignment or center RBAC restriction is added for this
operation. Customers retain GET access to their own services and cannot update sessions or flags. This supports standalone
and composite therapy services.

When adding sessions or updating flags, the assigned ProgramService, TherapyProgramService, parent Program, and its therapy/composite extension must be
active. The parent expires_at must be null or on/after today's local date. Cancelled, inactive, expired, missing-extension,
and unsupported parent-program records reject the update.

The write adds the supplied sessions_count increment to the current stored total using an ORM F expression. An allowance of 6
plus sessions_count=12 becomes 18. Responses return the resulting cumulative sessions_count.
sessions_used, sessions_cancelled, center selections, and redemption history stay unchanged. Standalone therapy
programs receive the same increment in their aggregate sessions_count in the same transaction. Composite programs
have no aggregate session-count field.

Flags may be sent without sessions_count. They update the shared parent Program for both standalone therapy and
composite programs, affecting every service under that parent. Omitted flags retain their stored values; explicit
false is applied. Both flags cannot be true. A resulting non-complimentary program requires an existing non-null
price. The operation does not create receipts or change credit_received. Each changed flag creates one program audit
entry attributed to the authenticated staff user; unchanged flags create no entry. Flag updates, audit entries, and
any session increments commit or roll back together. Response flags remain nested under program.is_complimentary
and program.is_credit. Do not send a nested program object as input.

The response is the complete GET detail shape with refreshed session totals. Repeating a successful request adds
the increment again; there is no idempotency-key support. Refresh the parent program and service lists after success.

##### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "019fb7e9-12aa-7261-9f30-a41766a24bc1",
    "program": {
      "id": "019fb7e8-ffde-716e-9ebc-4dbd2bb180fb",
      "uid": "P0001",
      "profile": {
        "id": "019ed45e-91bc-7c85-9e28-13720320d10c",
        "contact_email": "client@example.com",
        "phone": "+919876543210",
        "first_name": "Ravi",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-04-12",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": false,
        "created_at": "2026-10-24T10:00:00+05:30",
        "updated_at": "2026-10-24T10:00:00+05:30"
      },
      "program_type": "Therapy Program",
      "notes": null,
      "expires_at": "2026-12-31",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 1,
      "sessions_count": 18,
      "sessions_used": 1,
      "sessions_cancelled": 0,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "created_date": "2026-10-24",
      "cancelled_date": null,
      "is_active": true,
      "created_at": "2026-10-24T10:00:00+05:30",
      "updated_at": "2026-10-24T10:00:00+05:30"
    },
    "redeemable_centers": [
      {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Bengaluru"
      }
    ],
    "service": {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "name": "Recovery Therapy",
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
          "code": "C0001",
          "name": "Bengaluru"
        }
      ]
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "sessions_count": 18,
    "sessions_used": 1,
    "sessions_cancelled": 0,
    "redeem_code": "ABCD123456",
    "created_date": "2026-10-24",
    "created_by": null,
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

##### Errors

`400 Bad Request` — inactive, expired, or invalid program/service state:

```json
{
  "detail": "Cannot update an inactive, expired, or invalid therapy service."
}
```

Invalid resulting flags return 400 with detail.is_credit when both are true, or detail.price when a required stored
price is missing. Missing or non-therapy assigned service IDs return 404. Customers cannot use this update operation.

#### 3. List assigned therapy centers

Read all selected centers and their parent-program membership.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/redeemable-centers/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Query Parameters

| Name    | Required | Example | Notes                   |
|---------|----------|---------|-------------------------|
| `page`  | No       | 1       | Default 1.              |
| `limit` | No       | 10      | Default 10; maximum 50. |

##### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<center_uuid>",
      "code": "C0001",
      "name": "Bengaluru",
      "can_redeem": true
    }
  ]
}
```

##### Logic

Each assigned center is returned even if can_redeem is false. The flag checks only membership in the parent program's
redeemable_centers. It does not check active status, expiry, session balance, or catalogue availability. Missing
services and services outside customer ownership return 404; no assigned centers returns an empty page.

#### 4. List available therapy centers

List the parent program's redeemable centers before selecting additions to the assigned therapy service.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/available-redeemable-centers/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `019fb7e9-12aa-7261-9f30-a41766a24bc1` | Assigned ProgramService UUID, not the catalogue service ID. |

##### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Bengaluru` | Trimmed, case-insensitive name substring or code prefix. Blank applies no search filter. |
| `active` | No | `1` | `1` selects active centers; `0` selects inactive centers. Omitted or invalid values include both. |
| `page` | No | `1` | Defaults to 1. |
| `limit` | No | `10` | Defaults to 10; maximum 50. |

##### Response — `200 OK`

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
      "is_home_center": true,
      "can_redeem": true
    }
  ]
}
```

##### Logic

Admins and associates may read; customers may read only therapy services belonging to their own customer account.
The parent program supplies the candidate centers for both standalone and composite therapy services. This differs
from the program-level available-redeemable-centers API, which lists the customer profile's linked centers.

`exists` checks membership in therapy_service.redeemable_centers. `is_home_center` independently checks the parent
program customer profile's is_primary center assignment, including inactive assignments. A home center is returned
only if it is also a parent-program redeemable center; it can have exists=false. Missing primary assignments produce
is_home_center=false on every row. Service-selected centers outside the parent program are excluded from this list;
operation 3 continues to return them.

`can_redeem` retains operation 3's meaning of parent-program membership, so it is true for every row in this list.
These flags do not check expiry, remaining sessions, catalogue availability, or program/service active status.
Inactive centers are included by default. The existing PATCH still requires active parent-program centers and
active service/program records; discovery does not bypass those write rules.

Order is home center first, then exists=true, then center created_at descending and UUID descending. No matching
centers returns count=0 and data=[]. This GET does not modify selections; use operation 5 to append centers.

##### Errors

`404 Not Found` — missing therapy service or a service outside customer ownership:

```json
{
  "detail": "Therapy program service not found."
}
```

#### 5. Add therapy centers

Append selected centers without replacing existing assignments.

**Method:** `PATCH`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/redeemable-centers/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Payload

| Name          | Required | Example                  | Notes                                              |
|---------------|----------|--------------------------|----------------------------------------------------|
| `add_centers` | Yes      | [{"id":"<center_uuid>"}] | Nonempty list of objects; each object requires id. |

```json
{
  "add_centers": [
    {
      "id": "<center_uuid>"
    }
  ]
}
```

##### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "<program_service_uuid>"
  }
}
```

##### Logic

Admins may write; associates require X-Center-ID and active center RBAC access. Customers cannot write. Selected centers
must be active members of the parent program's redeemable centers. The service assignment, therapy extension, program,
and its therapy/composite extension must be active. Repeated centers create no duplicate links. Only declared
serializer fields are processed. Refresh operations 3 and 4 after success. This route has no POST operation.

#### 6. Cancel the therapy service

Cancel remaining therapy allowance with an audit reason and date.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/cancel/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Payload

| Name                  | Required | Example                              | Notes                                                |
|-----------------------|----------|--------------------------------------|------------------------------------------------------|
| `cancellation_reason` | No       | Cancelled at the customer's request. | Text, blank, or null.                                |
| `cancelled_date`      | No       | 2026-10-24                           | Defaults to the current local date; null is invalid. |

```json
{
  "cancellation_reason": "Cancelled at the customer's request.",
  "cancelled_date": "2026-10-24"
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Cancelled at the customer's request.",
    "cancelled_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "cancelled_at": "2026-10-24T10:00:00+05:30",
    "cancelled_date": "2026-10-24"
  }
}
```

##### Logic

Admins and associates may cancel. X-Center-ID is required and must identify an existing center. Already-cancelled
services and fully used therapy services return 400. Cancellation does not create an upload or alter catalogue coverage.

## Assessment mini ePRD

### Logical Flow

1. **Read the assigned assessment service** — Load the assessment identity, result counters, and cancellation state.
2. **Create assessment result metadata** — Create the result before attaching assessment files.
3. **Upload an assessment file** — Attach one report or raw file to the created assessment result.
4. **List assessment files** — Read all uploaded documents for the assigned assessment service.
5. **Delete an assessment file** — Delete one assessment document and refresh its file counters.
6. **Cancel the assessment service** — Cancel the assessment assignment while retaining existing result history.

### API Requests

#### 1. Read the assigned assessment service

Load the assessment identity, result counters, and cancellation state.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<program_service_uuid>",
    "service": {
      "id": "<catalogue_service_uuid>",
      "name": "Comprehensive Health Assessment",
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
    "fetch_count": 0,
    "fetch_results_count": 0,
    "fetch_documents_count": 0,
    "fetch_pending_count": 0,
    "created_date": "2026-10-24",
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

##### Logic

Admins and associates may use assessment operations; customers cannot. X-Center-ID is not required. There are no
assigned assessment-center links or center-alignment operations. The nested service contains basic catalogue identity
only.

#### 2. Create assessment result metadata

Create the result before attaching assessment files.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/results/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Payload

| Name                     | Required | Example        | Notes                                                       |
|--------------------------|----------|----------------|-------------------------------------------------------------|
| `product_id`             | Yes      | <product_uuid> | Active product with active provider and service assignment. |
| `document_type`          | Yes      | blood          | Must be allowed for the selected product.                   |
| `sample_collection_date` | No       | 2026-10-24     | ISO date or null.                                           |
| `report_generation_date` | No       | 2026-10-24     | ISO date or null.                                           |

```json
{
  "product_id": "<product_uuid>",
  "document_type": "blood",
  "sample_collection_date": "2026-10-24",
  "report_generation_date": null
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<result_uuid>",
    "product": {
      "id": "<product_uuid>",
      "name": "Blood Panel",
      "code": "PC-0001"
    },
    "provider_name": "Diagnostic Provider",
    "product_name": "Blood Panel",
    "result_mode": "Upload",
    "result_mode_code": "upload",
    "document_type": "Blood diagnostics Report",
    "document_type_code": "blood",
    "sample_collection_date": "2026-10-24",
    "report_generation_date": null,
    "documents_count": 0,
    "documents": [],
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30"
  }
}
```

##### Logic

Select the provider/product and allowed document type using the assessment-owned discovery APIs listed below. A
cancelled assessment cannot receive results. result_mode is server-controlled as upload; provider/product names are
snapshotted. Keep data.id as the result ID. Existing result product/document_type remain unchanged by PATCH; only dates
are editable.

#### 3. Upload an assessment file

Attach one report or raw file to the created assessment result.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/results/<result_id>/documents/`

##### Path Parameters

| Name        | Required | Example     | Notes                        |
|-------------|----------|-------------|------------------------------|
| `result_id` | Yes      | <result_id> | Assessment ServiceResult ID. |

##### Payload

Use `multipart/form-data`; send an actual binary file for `file`. The JSON example names the submitted fields.

| Name                | Required | Example       | Notes                                    |
|---------------------|----------|---------------|------------------------------------------|
| `file`              | Yes      | <binary file> | One nonempty file per multipart request. |
| `document_category` | Yes      | report        | report or raw.                           |

```json
{
  "file": "<binary file>",
  "document_category": "report"
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<assessment_document_uuid>",
    "file": "<file_url>",
    "filename": "assessment-report.pdf",
    "content_type": "application/pdf",
    "document_category": "Report file",
    "document_category_code": "report",
    "module_category": "Clinical Lab Diagnostics",
    "module_category_code": "clinical_lab_diagnostics",
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30"
  }
}
```

##### Logic

The result and its assigned assessment service must be active. The parent result supplies document_type; do not send
document_type, filename, content_type, file_hash, or result. The response contains module_category and
module_category_code, with no nested result field. Counts are updated after upload; no finalize request exists. Therapy
and consultation IDs cannot resolve through this assessment-only result lookup.

#### 4. List assessment files

Read all uploaded documents for the assigned assessment service.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/documents/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Query Parameters

| Name                | Required | Example                  | Notes                                        |
|---------------------|----------|--------------------------|----------------------------------------------|
| `result`            | No       | <result_uuid>            | Filter by assessment result ID.              |
| `document_type`     | No       | blood                    | Exact parent-result type code.               |
| `document_category` | No       | report                   | Exact report/raw code.                       |
| `module_category`   | No       | clinical_lab_diagnostics | Maps to parent-result document types.        |
| `search`            | No       | report                   | Trimmed case-insensitive filename substring. |
| `page`              | No       | 1                        | Default 1.                                   |
| `limit`             | No       | 10                       | Default 10; maximum 50.                      |

##### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<assessment_document_uuid>",
      "file": "<file_url>",
      "filename": "assessment-report.pdf",
      "content_type": "application/pdf",
      "document_category": "Report file",
      "document_category_code": "report",
      "module_category": "Clinical Lab Diagnostics",
      "module_category_code": "clinical_lab_diagnostics",
      "is_active": true,
      "created_at": "2026-10-24T10:00:00+05:30",
      "updated_at": "2026-10-24T10:00:00+05:30"
    }
  ]
}
```

##### Logic

Historical results and files remain readable after cancellation. The backend filters by the assigned assessment service
and does not expose consultation files or therapy uploads.

#### 5. Delete an assessment file

Delete one assessment document and refresh its file counters.

**Method:** `DELETE`

**URL:** `<baseURL>/programs/program-services/assessment-services/documents/<document_id>/`

##### Path Parameters

| Name          | Required | Example       | Notes                          |
|---------------|----------|---------------|--------------------------------|
| `document_id` | Yes      | <document_id> | Assessment ServiceDocument ID. |

##### Response — `200 OK`

```json
{
  "detail": "Deleted successfully."
}
```

##### Logic

document_id identifies an assessment ServiceDocument. This operation is assessment-only. Database counters are refreshed
and stored-file cleanup is scheduled after commit.

#### 6. Cancel the assessment service

Cancel the assessment assignment while retaining existing result history.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/cancel/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Payload

| Name                  | Required | Example                              | Notes                                                |
|-----------------------|----------|--------------------------------------|------------------------------------------------------|
| `cancellation_reason` | No       | Cancelled at the customer's request. | Text, blank, or null.                                |
| `cancelled_date`      | No       | 2026-10-24                           | Defaults to the current local date; null is invalid. |

```json
{
  "cancellation_reason": "Cancelled at the customer's request.",
  "cancelled_date": "2026-10-24"
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Cancelled at the customer's request.",
    "cancelled_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "cancelled_at": "2026-10-24T10:00:00+05:30",
    "cancelled_date": "2026-10-24"
  }
}
```

##### Logic

No center header or center selection is needed. Already-cancelled services return 400. Existing results and documents
remain stored.

### Assessment-owned supporting operations

Use the assessment provider/product endpoints below to choose an active product, then GET
`<baseURL>/products/<product_id>/allowed-documents/` and submit one of its returned `value` codes. Allowed-document
discovery returns `detail: "Allowed document types retrieved."` and a `data` array of
`{ "display_name": "Blood diagnostics Report", "value": "blood" }` objects.

The category aliases for assessment result/request operations are listed below:

| Method             | Category-owned URL                                                                                    |
|--------------------|-------------------------------------------------------------------------------------------------------|
| GET                | `<baseURL>/programs/program-services/assessment-services/<program_service_id>/providers/`             |
| GET                | `<baseURL>/programs/program-services/assessment-services/<program_service_id>/products/`              |
| GET                | `<baseURL>/programs/program-services/assessment-services/<program_service_id>/results/`               |
| GET, PATCH, DELETE | `<baseURL>/programs/program-services/assessment-services/results/<result_id>/`                        |
| GET                | `<baseURL>/programs/program-services/assessment-services/results/<result_id>/documents/`              |
| GET, POST          | `<baseURL>/programs/program-services/assessment-services/<program_service_id>/result-requests/`       |
| POST               | `<baseURL>/programs/program-services/assessment-services/<program_service_id>/request-report/`        |
| GET, PATCH         | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/`               |
| GET                | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/files/`         |
| POST               | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/confirm-order/` |
| POST               | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/refetch/`       |
| POST               | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/cancel/`        |

Existing clients may continue using these URLs; each resolves to the same view as its category alias:

| Existing URL                                                                      | Category alias                                                                                        |
|-----------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------|
| `<baseURL>/programs/program-services/results/<result_id>/`                        | `<baseURL>/programs/program-services/assessment-services/results/<result_id>/`                        |
| `<baseURL>/programs/program-services/results/<result_id>/documents/`              | `<baseURL>/programs/program-services/assessment-services/results/<result_id>/documents/`              |
| `<baseURL>/programs/program-services/result-requests/<request_id>/`               | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/`               |
| `<baseURL>/programs/program-services/result-requests/<request_id>/files/`         | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/files/`         |
| `<baseURL>/programs/program-services/result-requests/<request_id>/confirm-order/` | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/confirm-order/` |
| `<baseURL>/programs/program-services/result-requests/<request_id>/refetch/`       | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/refetch/`       |
| `<baseURL>/programs/program-services/result-requests/<request_id>/cancel/`        | `<baseURL>/programs/program-services/assessment-services/result-requests/<request_id>/cancel/`        |
| `<baseURL>/programs/program-result-documents/<document_id>/`                      | `<baseURL>/programs/program-services/assessment-services/documents/<document_id>/`                    |

## Consultation mini ePRD

### Logical Flow

1. **Read the assigned consultation service** — Load the consultation identity and its documents_count.
2. **Upload a consultation document** — Create one document with its file and consultation metadata in a single request.
3. **List consultation documents** — Read uploaded documents with optional type and date filters.
4. **Read a consultation document** — Load one document, its file URL, and its creator.
5. **Delete a consultation document** — Remove the document and its file.
6. **Cancel the consultation service** — Cancel the assigned consultation and retain its existing documents.

### API Requests

#### 1. Read the assigned consultation service

Load the consultation identity and its documents_count.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<program_service_uuid>",
    "program": {
      "id": "<program_uuid>",
      "uid": "P0001",
      "profile": {
        "id": "<profile_uuid>",
        "contact_email": "client@example.com",
        "phone": "+919876543210",
        "first_name": "Ravi",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-04-12",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": false,
        "created_at": "2026-10-24T10:00:00+05:30",
        "updated_at": "2026-10-24T10:00:00+05:30"
      },
      "program_type": "Composite",
      "notes": null,
      "expires_at": "2026-12-31",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 1,
      "sessions_count": null,
      "sessions_used": null,
      "sessions_cancelled": null,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "created_date": "2026-10-24",
      "cancelled_date": null,
      "is_active": true,
      "created_at": "2026-10-24T10:00:00+05:30",
      "updated_at": "2026-10-24T10:00:00+05:30"
    },
    "service": {
      "id": "<catalogue_service_uuid>",
      "name": "Nutrition Consultation",
      "service_category": "Consultation",
      "service_category_code": "consultation",
      "image": null,
      "centers": null
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "documents_count": 1,
    "created_date": "2026-10-24",
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

##### Logic

Admins may read; associates need X-Center-ID, active center RBAC access, and an owning/redeemable-center match to the
composite program. Customers cannot use this flow. There are no assigned consultation-center alignment operations.
Catalogue coverage and the parent program's access scope remain separate.

#### 2. Upload a consultation document

Upload one file directly on a new document. No separate metadata or child-file creation request is needed.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/documents/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `<program_service_uuid>` | Assigned consultation ProgramService ID. |

##### Payload

Use multipart/form-data. The file placeholder in this JSON illustrates the multipart field names; attach the binary
file in the actual request rather than sending a JSON string.

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | Yes | consultation_notes | questionnaire, consultation_notes, or post_consultation. |
| `file` | Yes | consultation-notes.pdf | One nonempty uploaded file. |
| `consultation_type` | No | baseline | baseline or followups; defaults to baseline. |
| `consultation_date` | No | 2026-10-24 | Defaults to the current local date; future dates are rejected. |

```json
{
  "document_type": "consultation_notes",
  "file": "<binary file: consultation-notes.pdf>",
  "consultation_type": "baseline",
  "consultation_date": "2026-10-24"
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "<consultation_document_uuid>",
    "document_type": "Consultation Notes",
    "document_type_code": "consultation_notes",
    "consultation_type": "Baseline",
    "consultation_type_code": "baseline",
    "consultation_date": "2026-10-24",
    "file": "https://example.com/media/consultations/consultation-notes.pdf",
    "filename": "consultation-notes.pdf",
    "content_type": "application/pdf",
    "files_count": 1,
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30"
  }
}
```

##### Logic

Admins and associates with active center RBAC access may upload. Associates require X-Center-ID and the consultation
must belong to that center or be redeemable there. Missing or out-of-scope services return 404. Inactive/cancelled or
expired consultations reject uploads with 400. Customers cannot use these consultation-document APIs.

Each POST creates a new document. Multiple documents may have the same document_type, consultation_type, and
consultation_date; neither uniqueness checks nor file replacement are applied. Keep the three existing document types.

The backend records the authenticated user as created_by. Clients cannot set creator, filename, content type, hash, or
counts. The hash is stored internally and excluded from responses. Creator output may become null if the user is deleted.

Creation and count updates run in one transaction. Each document has files_count = 1. Consultation service responses,
including consultation entries in composite service lists, expose a single documents_count: the number of uploaded
consultation documents. Duplicate types/dates each contribute one to this count; deletion reduces it by one.
The count is stored on the consultation service and updated during document creation/deletion. Service GETs read
the stored value; they do not count documents at request time. Composite service lists read their synchronized stored
documents_count value too.

The composite program's existing consultation_documents_count remains the total across all of that program's
consultations and is updated on upload and deletion. No counter is added to the base Program model.

#### 3. List consultation documents

List the consultation's uploaded documents and direct file URLs.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/documents/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `<program_service_uuid>` | Assigned consultation ProgramService ID. |

##### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | 1 | Default: 1. |
| `limit` | No | 10 | Default: 10; maximum: 50. |
| `document_type` | No | consultation_notes | questionnaire, consultation_notes, or post_consultation. |
| `consultation_type` | No | baseline | baseline or followups. |
| `consultation_date` | No | 2026-10-24 | Exact ISO date. |

##### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<consultation_document_uuid>",
      "document_type": "Consultation Notes",
      "document_type_code": "consultation_notes",
      "consultation_type": "Baseline",
      "consultation_type_code": "baseline",
      "consultation_date": "2026-10-24",
      "file": "https://example.com/media/consultations/consultation-notes.pdf",
      "filename": "consultation-notes.pdf",
      "content_type": "application/pdf",
      "files_count": 1,
      "created_by": {
        "id": "<user_uuid>",
        "email": "admin@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": null
      },
      "is_active": true,
      "created_at": "2026-10-24T10:00:00+05:30",
      "updated_at": "2026-10-24T10:00:00+05:30"
    }
  ]
}
```

##### Logic

Uses the same staff and center ownership scope as operation 2. Documents are newest first by created_at.
An accessible consultation without documents returns count = 0 and data = []. Invalid declared filter values return
400. Retained documents remain readable after cancellation or expiry.

#### 4. Read a consultation document

Read the complete document and its file URL.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/documents/<document_id>/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_id` | Yes | `<consultation_document_uuid>` | ConsultationDocument ID. |

##### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<consultation_document_uuid>",
    "document_type": "Consultation Notes",
    "document_type_code": "consultation_notes",
    "consultation_type": "Baseline",
    "consultation_type_code": "baseline",
    "consultation_date": "2026-10-24",
    "file": "https://example.com/media/consultations/consultation-notes.pdf",
    "filename": "consultation-notes.pdf",
    "content_type": "application/pdf",
    "files_count": 1,
    "created_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "2026-10-24T10:00:00+05:30",
    "updated_at": "2026-10-24T10:00:00+05:30"
  }
}
```

##### Logic

Uses the same staff and center ownership scope as operation 2. Missing or out-of-scope documents return 404.
The existing `<baseURL>/programs/program-services/consultation-documents/<document_id>/` URL remains an alias
for this same GET and DELETE view.

#### 5. Delete a consultation document

Delete one document and its stored file together.

**Method:** `DELETE`

**URL:** `<baseURL>/programs/program-services/consultation-services/documents/<document_id>/`

##### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_id` | Yes | `<consultation_document_uuid>` | ConsultationDocument ID. |

##### Response — `200 OK`

```json
{
  "detail": "Deleted successfully."
}
```

##### Logic

Uses the same staff and center ownership scope as operation 2. Inactive/cancelled or expired consultations reject
deletion with 400. The document row is deleted and consultation/composite counts are refreshed in one transaction.
Storage deletion is scheduled after commit; rolled-back deletions do not remove the stored file.

#### 6. Cancel the consultation service

Cancel the assigned consultation and retain its existing document history.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/cancel/`

##### Path Parameters

| Name                 | Required | Example              | Notes                                             |
|----------------------|----------|----------------------|---------------------------------------------------|
| `program_service_id` | Yes      | <program_service_id> | Assigned ProgramService ID, not the catalogue ID. |

##### Payload

| Name                  | Required | Example                              | Notes                                                |
|-----------------------|----------|--------------------------------------|------------------------------------------------------|
| `cancellation_reason` | No       | Cancelled at the customer's request. | Text, blank, or null.                                |
| `cancelled_date`      | No       | 2026-10-24                           | Defaults to the current local date; null is invalid. |

```json
{
  "cancellation_reason": "Cancelled at the customer's request.",
  "cancelled_date": "2026-10-24"
}
```

##### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Cancelled at the customer's request.",
    "cancelled_by": {
      "id": "<user_uuid>",
      "email": "admin@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": null
    },
    "cancelled_at": "2026-10-24T10:00:00+05:30",
    "cancelled_date": "2026-10-24"
  }
}
```

##### Logic

The cancellation route and existing behavior are retained. Admins and associates may cancel; this cancellation endpoint
does not require X-Center-ID or consultation document RBAC. Already-cancelled services return 400. Consultation documents
remain readable; uploads and deletions are rejected after cancellation.

### Consultation document routes and client changes

The document collection supports GET and POST. Both document detail URLs support GET and DELETE only; PATCH and PUT
return 405. Consultation cancellation retains its existing route and behavior.

ConsultationDocumentFile and its separate workflow have been removed. The following file-only URLs are no longer
registered and have no compatibility adapters:

- `<baseURL>/programs/program-services/consultation-services/<program_service_id>/files/`
- `<baseURL>/programs/program-services/consultation-documents/<document_id>/files/`
- `<baseURL>/programs/program-services/consultation-document-files/<file_id>/`
- `<baseURL>/programs/program-services/consultation-services/documents/<document_id>/files/`
- `<baseURL>/programs/program-services/consultation-services/document-files/<file_id>/`

Clients using metadata-only POSTs or file-only URLs must use operation 2 and read file URLs directly from documents.
There is no document-edit or file-replacement endpoint. Create another document and, when appropriate, delete the old
one. Assessment upload/result/request routes remain unchanged. Therapy has no file-upload workflow.

The model changes require a user-generated migration. No existing consultation document/file data needs transfer.
