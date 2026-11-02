# Composite Program Services and Redemption — Frontend ePRD

Manage an assigned composite from its detail page through category-specific service retrieval, edits, center selection, assessment documents, and direct therapy redemption.

Examples illustrate the final source contract; they are not captured responses from the supplied program’s database record. Use `<baseURL>` for the configured backend host. Authorization: `Bearer <token>`. Requests are for admin/associate staff unless a block explicitly describes existing customer read access. Send `X-Center-ID: <center_uuid>` for the selected center; mandatory header and role requirements are stated where enforced. JSON mutations use `Content-Type: application/json`; file uploads use multipart/form-data.

## Logical Flow

1. **Retrieve the composite program** — Open the assigned composite and retain its identifiers for subsequent operations.
2. **Edit supported program fields** — Update program metadata without changing the assigned template or service occurrences.
3. **Retrieve program audit history** — Show persisted program metadata changes after edits.
4. **Cancel the composite program** — Cancel the parent composite and remaining therapy entitlements.
5. **List every service in this composite** — Load the authoritative assigned-service collection and switch category tabs.
6. **List a profile’s composite services** — Find service occurrences across a customer profile’s composites or narrow to this program.
7. **Retrieve catalogue services for add-ons** — Select active catalogue IDs for assessment, therapy or consultation occurrences.
8. **Add service occurrences to the composite** — Append repeatable assessment, therapy and consultation assignments.
9. **Retrieve an individual therapy service** — Read the assigned therapy service’s counters, program and selected centers.
10. **Add redemption centers to an existing composite therapy service** — Manually configure legacy services or append further selected parent centers.
11. **Look up a therapy service by redemption code** — Resolve a scanned code to its assigned service occurrence before redemption.
12. **Redeem therapy sessions** — Consume one session or all remaining sessions for the assigned therapy service.
13. **Retrieve therapy redemption history** — Show persisted session consumption and cancellation entries.
14. **Cancel an assigned therapy service** — Cancel the service’s unused allowance while preserving its history.
15. **Retrieve an individual assessment service** — Open the assigned assessment occurrence and its current result/document counters.
16. **List providers for an assessment** — Discover available providers and their configured fetch, booking and confirmation input keys.
17. **List products for the assessment** — Select a product assigned to this service before ordering, fetching or creating results.
18. **Retrieve allowed result document types** — Populate the manual-result document type selector for the chosen product.
19. **Create an assessment report order** — Save provider booking inputs as a pending order before confirmation.
20. **List assessment result requests** — Show pending orders, fetch jobs, statuses, results and available request edits.
21. **Fetch existing provider results** — Create a provider fetch request without creating a new report order.
22. **Retrieve an individual result request** — Inspect one order/fetch request and its saved provider inputs.
23. **Edit a pending report order** — Correct booking/profile inputs before submitting an order.
24. **Confirm a report order** — Validate confirmation inputs and queue provider submission.
25. **List every request attachment** — Retrieve request files omitted from the three-file preview.
26. **Refetch a result request** — Requeue a supported submitted order or fetch job to retrieve current provider results.
27. **Cancel a result request** — Mark an unfinished request cancelled.
28. **List assessment results** — Retrieve manually uploaded and provider-created result records for the assigned assessment.
29. **Create a manual assessment result** — Create result metadata before uploading a document.
30. **Retrieve an individual assessment result** — Read one result and its document preview.
31. **Edit assessment result dates** — Correct collection or report dates on an existing result.
32. **Delete an assessment result** — Remove a result and its attached documents.
33. **List every document for an assessment service** — Show the complete document collection across the service’s results.
34. **List every document for a result** — Retrieve documents omitted from the result’s three-document preview.
35. **Upload an assessment result document** — Attach an actual report/raw file to the existing result.
36. **Delete an individual assessment document** — Remove one file without deleting the result metadata.
37. **Cancel an assigned assessment service** — Deactivate one assessment occurrence.
38. **Retrieve an individual consultation service** — Read the assigned consultation’s parent program, catalogue service and lifecycle metadata.
39. **Retrieve profile centers for center selection** — Resolve center UUIDs and names when selecting parent and per-service redemption centers.
40. **Retrieve template services before assignment** — Read active template categories, therapy quantities and the catalogue IDs needed for per-service center selections.
41. **Assign a composite through the profile route** — Create the composite with explicit therapy redemption-center selections.
42. **Assign a composite through the center route** — Create the same category-specific assignments from a center-scoped customer selection.

Service operations start from the assigned IDs in the complete service lists. The supplementary center/template/assignment requests at the end configure new composites without changing the starting detail flow. Reload the composite and affected full lists after mutations; previews and counters are server-owned. No appointment APIs are part of this ePRD.

## API Requests

### 1. Retrieve the composite program

Open the assigned composite and retain its identifiers for subsequent operations.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/programs/01a162fe-2739-7663-b059-fdb6d37f9a16/`

**Access:** Admin or associate. Current detail view uses role checks; category lists and new individual consultation/center actions apply their separately documented center scope.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite/base Program UUID; the first URL shows the supplied example. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
    "uid": "P0123",
    "name": "Wellness Programme",
    "assessment_type": "Baseline",
    "assessment_type_code": "baseline",
    "profile": {
      "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
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
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "center": {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    },
    "composite_template": {
      "id": "01a162da-baad-773a-92af-b93a3138d3f4",
      "code": "CMP0001",
      "name": "Wellness Programme",
      "is_active": true
    },
    "program_type": "composite",
    "notes": "Customer wellness programme",
    "expires_at": "2026-12-31",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": [
      {
        "id": "01a162ff-1000-7000-8000-000000000001",
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
              "name": "Biopeak Bengaluru",
              "image": null,
              "address": "Indiranagar, Bengaluru",
              "address_line_1": "100 Example Road",
              "address_line_2": null,
              "city": "Bengaluru",
              "state": "Karnataka",
              "country": "India",
              "pincode": "560038",
              "staff_count": 4,
              "inactive_staff_count": 0,
              "customer_count": 20,
              "inactive_customer_count": 0,
              "is_active": true,
              "created_at": "2026-10-22T10:00:00+05:30",
              "updated_at": "2026-10-22T10:00:00+05:30"
            }
          ]
        },
        "service_assignment_type": "Standalone",
        "service_assignment_type_code": "standalone",
        "redeemable_centers": [
          {
            "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
            "code": "C0001",
            "name": "Biopeak Bengaluru"
          }
        ],
        "sessions_count": 4,
        "sessions_used": 0,
        "sessions_cancelled": 0,
        "redeem_code": "RC123456",
        "can_redeem": true,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-22",
        "created_by": {
          "id": "019f1000-0000-7000-8000-000000000006",
          "email": "staff@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-22T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30"
      }
    ],
    "services_count": 3,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 1,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-22",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    }
  }
}
```

#### Logic

The supplied UUID is also the base Program UUID. services is a preview of at most three entries and can be null; use request 5 for the complete list. Category counters count assigned occurrences, not therapy sessions, and include cancelled lines. add_ons_count overlaps category counters. service remains the catalogue representation; redeemable_centers on an assigned service contains its therapy selections (empty for other categories). Parent redeemable_centers currently serializes code and name without id; retain selected UUIDs from assignment or use the profile-center lookup in request 39. can_redeem for therapy includes entitlement, expiry, remaining sessions and live availability; consultation returns false. Without a center context, therapy checks whether any selected center is eligible.

### 2. Edit supported program fields

Update program metadata without changing the assigned template or service occurrences.

**Method:** `PATCH`

**URL:** `<baseURL>/programs/composites/programs/<program_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite/base Program UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `notes` | No | `Updated notes` | Text, blank or null. |
| `expires_at` | No | `2026-12-31` | Date or null; a non-null date cannot precede today. |
| `is_complimentary` | No | `false` | Currently persisted by the nested program update. |
| `price` | No | `12000.00` | Decimal string or null; up to 10 digits and 2 decimal places. |

```json
{
  "notes": "Updated notes",
  "expires_at": "2026-12-31"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
    "uid": "P0123",
    "name": "Wellness Programme",
    "assessment_type": "Baseline",
    "assessment_type_code": "baseline",
    "profile": {
      "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
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
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "center": {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    },
    "composite_template": {
      "id": "01a162da-baad-773a-92af-b93a3138d3f4",
      "code": "CMP0001",
      "name": "Wellness Programme",
      "is_active": true
    },
    "program_type": "composite",
    "notes": "Updated notes",
    "expires_at": "2026-12-31",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": [
      {
        "id": "01a162ff-1000-7000-8000-000000000001",
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
              "name": "Biopeak Bengaluru",
              "image": null,
              "address": "Indiranagar, Bengaluru",
              "address_line_1": "100 Example Road",
              "address_line_2": null,
              "city": "Bengaluru",
              "state": "Karnataka",
              "country": "India",
              "pincode": "560038",
              "staff_count": 4,
              "inactive_staff_count": 0,
              "customer_count": 20,
              "inactive_customer_count": 0,
              "is_active": true,
              "created_at": "2026-10-22T10:00:00+05:30",
              "updated_at": "2026-10-22T10:00:00+05:30"
            }
          ]
        },
        "service_assignment_type": "Standalone",
        "service_assignment_type_code": "standalone",
        "redeemable_centers": [
          {
            "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
            "code": "C0001",
            "name": "Biopeak Bengaluru"
          }
        ],
        "sessions_count": 4,
        "sessions_used": 0,
        "sessions_cancelled": 0,
        "redeem_code": "RC123456",
        "can_redeem": true,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-22",
        "created_by": {
          "id": "019f1000-0000-7000-8000-000000000006",
          "email": "staff@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-22T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30"
      }
    ],
    "services_count": 3,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 1,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-22",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    }
  }
}
```

#### Logic

Send only fields being edited. name, assessment_type, profile_id, composite_template_id and therapy_service_centers are discarded by this update. Do not send parent redeemable_centers: replacement is not implemented by this PATCH. Price/complimentary validation on creation must not be assumed to run on this update. Reload detail and history after success.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "expires_at": "Expiry date cannot be earlier than today's date."
  }
}
```

### 3. Retrieve program audit history

Show persisted program metadata changes after edits.

**Method:** `GET`

**URL:** `<baseURL>/programs/<program_id>/history/`

**Access:** Admin or associate with active X-Center-ID assignment; associate must have access to a program owning/redeemable center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite/base Program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Page size, maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000010",
      "changed_field": "Notes",
      "changed_field_code": "notes",
      "previous_value": "Customer wellness programme",
      "current_value": "Updated notes",
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "created_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Newest changes first. Values are serialized text or null. This history tracks configured program fields; service center additions and therapy redemption history are separate resources.

### 4. Cancel the composite program

Cancel the parent composite and remaining therapy entitlements.

**Method:** `POST`

**URL:** `<baseURL>/programs/composites/programs/<program_id>/cancel/`

**Access:** Admin or associate with PackagesPermission. X-Center-ID required for both; program must be owned by or redeemable at that center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite/base Program UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `cancellation_reason` | No | `Customer request` | Text, blank or null. |
| `cancelled_date` | No | `2026-10-22` | Defaults to the current local date. |

```json
{
  "cancellation_reason": "Customer request",
  "cancelled_date": "2026-10-22"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Customer request",
    "cancelled_date": "2026-10-22",
    "cancelled_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "cancelled_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Rejects an already inactive parent or any program with service documents. Existing cancellation deactivates the parent and its active therapy service lines; do not assume assessment/consultation line flags are rewritten. Reload parent and service lists.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Composite program is already cancelled."
}
```

`400 Bad Request`

```json
{
  "detail": "Composite program cannot be cancelled since it has documents."
}
```

### 5. List every service in this composite

Load the authoritative assigned-service collection and switch category tabs.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/programs/<program_id>/services/`

**Access:** Admin or associate with active X-Center-ID assignment and access to the program at that center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite/base Program UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `therapy` | assessment, therapy or consultation; exact single value. |
| `assignment_type` | No | `add_on` | standalone or add_on. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01a162ff-1000-7000-8000-000000000001",
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
            "name": "Biopeak Bengaluru",
            "image": null,
            "address": "Indiranagar, Bengaluru",
            "address_line_1": "100 Example Road",
            "address_line_2": null,
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560038",
            "staff_count": 4,
            "inactive_staff_count": 0,
            "customer_count": 20,
            "inactive_customer_count": 0,
            "is_active": true,
            "created_at": "2026-10-22T10:00:00+05:30",
            "updated_at": "2026-10-22T10:00:00+05:30"
          }
        ]
      },
      "service_assignment_type": "Standalone",
      "service_assignment_type_code": "standalone",
      "redeemable_centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
          "code": "C0001",
          "name": "Biopeak Bengaluru"
        }
      ],
      "sessions_count": 4,
      "sessions_used": 0,
      "sessions_cancelled": 0,
      "redeem_code": "RC123456",
      "can_redeem": true,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "fetch_count": 0,
      "fetch_results_count": 0,
      "fetch_documents_count": 0,
      "fetch_pending_count": 0,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-22",
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Omit category for all categories. This endpoint does not implement search or active filters. Non-therapy session counters/redeem_code are null and redeemable_centers is []. Use each outer id for individual service operations.

### 6. List a profile’s composite services

Find service occurrences across a customer profile’s composites or narrow to this program.

**Method:** `GET`

**URL:** `<baseURL>/profiles/<profile_id>/programs/composite-program-services/`

**Access:** Admin or associate. X-Center-ID is required; profile must be assigned to the center, and associates must also be assigned to the profile there.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019e20ea-5d4d-7356-b759-21546cfd8695` | Customer profile UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `consultation` | assessment, therapy or consultation; takes precedence over service_category. |
| `service_category` | No | `therapy` | Backward-compatible category name. |
| `assignment_type` | No | `add_on` | standalone or add_on. |
| `composite_program` | No | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Assigned composite UUID. |
| `search` | No | `Recovery` | Case-insensitive catalogue service name substring. |
| `active` | No | `1` | 0 or 1; omitted returns both. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Default 10; maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01a162ff-1000-7000-8000-000000000001",
      "composite_program": {
        "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
        "uid": "P0123",
        "name": "Wellness Programme",
        "template": {
          "id": "01a162da-baad-773a-92af-b93a3138d3f4",
          "code": "CMP0001",
          "name": "Wellness Programme",
          "is_active": true
        }
      },
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
            "name": "Biopeak Bengaluru",
            "image": null,
            "address": "Indiranagar, Bengaluru",
            "address_line_1": "100 Example Road",
            "address_line_2": null,
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560038",
            "staff_count": 4,
            "inactive_staff_count": 0,
            "customer_count": 20,
            "inactive_customer_count": 0,
            "is_active": true,
            "created_at": "2026-10-22T10:00:00+05:30",
            "updated_at": "2026-10-22T10:00:00+05:30"
          }
        ]
      },
      "redeemable_centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
          "code": "C0001",
          "name": "Biopeak Bengaluru"
        }
      ],
      "assignment_type": "Standalone",
      "assignment_type_code": "standalone",
      "sessions_count": 4,
      "sessions_used": 0,
      "sessions_cancelled": 0,
      "redeem_code": "RC123456",
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "can_redeem": true,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-22",
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Only composite-parent services are included. A literal pipe-separated category is not a multi-select filter; invalid choices return 400. Retain existing per-profile and per-center restrictions.

### 7. Retrieve catalogue services for add-ons

Select active catalogue IDs for assessment, therapy or consultation occurrences.

**Method:** `GET`

**URL:** `<baseURL>/services/`

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `therapy` | assessment, therapy or consultation. |
| `active` | No | `1` | 0 or 1; use 1 for add-on selection. |
| `search` | No | `Recovery` | Name prefix/substring. |
| `center_id` | No | `019ed45d-d6c4-7534-830e-501019fd98dd` | Optional repeatable catalogue-center filter; omit to avoid filtering out currently unavailable services. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

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
      "centers_count": 1,
      "care_template": null,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30",
      "is_active": true,
      "is_locked": true,
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      }
    }
  ]
}
```

#### Logic

Use catalogue id in add_services[].id. Selecting a service does not require current availability at the program’s centers. Catalogue center previews and assigned therapy center selections are different collections.

### 8. Add service occurrences to the composite

Append repeatable assessment, therapy and consultation assignments.

**Method:** `POST`

**URL:** `<baseURL>/programs/composites/add-ons/`

**Access:** Admin or associate with active X-Center-ID assignment; associate must have access to the target program.

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_program_id` | Yes | `01a162fe-2739-7663-b059-fdb6d37f9a16` | Existing active, non-expired composite. |
| `add_services` | Yes | `Array` | Nonempty list; repeated catalogue IDs create separate occurrences. |
| `add_services[].id` | Yes | `019e1622-403b-74d1-a991-df3b388b4ac8` | Active catalogue service UUID. |
| `add_services[].sessions_count` | Therapy only | `2` | Positive integer required for therapy; omit/null for assessment and consultation. |
| `add_services[].centers` | Therapy only | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Required nonempty {id} reference list for therapy; omit for assessment and consultation. |
| `add_services[].centers[].id` | Yes per center | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID; use the existing {id} reference pattern. |

```json
{
  "composite_program_id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
  "add_services": [
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "sessions_count": 2,
      "centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
        }
      ]
    },
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac9"
    },
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4aca"
    }
  ]
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
    "uid": "P0123",
    "name": "Wellness Programme",
    "assessment_type": "Baseline",
    "assessment_type_code": "baseline",
    "profile": {
      "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
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
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "center": {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    },
    "composite_template": {
      "id": "01a162da-baad-773a-92af-b93a3138d3f4",
      "code": "CMP0001",
      "name": "Wellness Programme",
      "is_active": true
    },
    "program_type": "composite",
    "notes": "Customer wellness programme",
    "expires_at": "2026-12-31",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": [
      {
        "id": "01a162ff-1000-7000-8000-000000000001",
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
              "name": "Biopeak Bengaluru",
              "image": null,
              "address": "Indiranagar, Bengaluru",
              "address_line_1": "100 Example Road",
              "address_line_2": null,
              "city": "Bengaluru",
              "state": "Karnataka",
              "country": "India",
              "pincode": "560038",
              "staff_count": 4,
              "inactive_staff_count": 0,
              "customer_count": 20,
              "inactive_customer_count": 0,
              "is_active": true,
              "created_at": "2026-10-22T10:00:00+05:30",
              "updated_at": "2026-10-22T10:00:00+05:30"
            }
          ]
        },
        "service_assignment_type": "Standalone",
        "service_assignment_type_code": "standalone",
        "redeemable_centers": [
          {
            "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
            "code": "C0001",
            "name": "Biopeak Bengaluru"
          }
        ],
        "sessions_count": 4,
        "sessions_used": 0,
        "sessions_cancelled": 0,
        "redeem_code": "RC123456",
        "can_redeem": true,
        "results_count": 0,
        "documents_count": 0,
        "reports_count": 0,
        "raw_data_count": 0,
        "fetch_count": 0,
        "fetch_results_count": 0,
        "fetch_documents_count": 0,
        "fetch_pending_count": 0,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-22",
        "created_by": {
          "id": "019f1000-0000-7000-8000-000000000006",
          "email": "staff@example.com",
          "first_name": "Asha",
          "last_name": "Rao",
          "image": null,
          "last_login": "2026-10-22T10:00:00+05:30"
        },
        "is_active": true,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30"
      }
    ],
    "services_count": 6,
    "add_ons_count": 3,
    "assessment_services_count": 2,
    "therapy_services_count": 2,
    "consultation_services_count": 2,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-22",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    }
  }
}
```

#### Logic

Each therapy selection must be an active parent redeemable center. No catalogue availability check occurs here. Therapy gets its requested session allowance; assessment and consultation get their own extension records without counters. Existing pricing and template membership are unchanged. Response services remains a preview; reload request 5 for all occurrences.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "add_services": "Select at least one redemption center."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "add_services": "Centers must be active members of the program's redeemable centers."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "add_services": "Center selections are only supported for therapy service entries."
  }
}
```

### 9. Retrieve an individual therapy service

Read the assigned therapy service’s counters, program and selected centers.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/`

**Access:** Admin or associate; existing endpoint also permits customers to read only their own assigned therapy services.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000001` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "01a162ff-1000-7000-8000-000000000001",
    "program": {
      "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
      "uid": "P0123",
      "profile": {
        "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
        "contact_email": "client@example.com",
        "phone": "+91-9876543210",
        "first_name": "Rohan",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-05-12",
        "image": null,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30",
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": true
      },
      "program_type": "Composite",
      "notes": "Customer wellness programme",
      "expires_at": "2026-12-31",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 3,
      "sessions_cancelled": null,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-22",
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
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
          "name": "Biopeak Bengaluru",
          "image": null,
          "address": "Indiranagar, Bengaluru",
          "address_line_1": "100 Example Road",
          "address_line_2": null,
          "city": "Bengaluru",
          "state": "Karnataka",
          "country": "India",
          "pincode": "560038",
          "staff_count": 4,
          "inactive_staff_count": 0,
          "customer_count": 20,
          "inactive_customer_count": 0,
          "is_active": true,
          "created_at": "2026-10-22T10:00:00+05:30",
          "updated_at": "2026-10-22T10:00:00+05:30"
        }
      ]
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "redeemable_centers": [
      {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "sessions_count": 4,
    "sessions_used": 0,
    "sessions_cancelled": 0,
    "redeem_code": "RC123456",
    "created_date": "2026-10-22",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

#### Logic

Use the assigned id from request 5/6. Top-level redeemable_centers is the complete stored selection, including selections that later become unavailable. Program-level standalone therapy aggregate counters do not exist on a composite parent; sessions_count and sessions_used remain on this individual service.

### 10. Add redemption centers to an existing composite therapy service

Manually configure legacy services or append further selected parent centers.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/redeemable-centers/`

**Access:** Admin or associate with active X-Center-ID assignment and access to the composite at that center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000001` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `add_redeemable_centers` | Yes | `Array` | Nonempty list; append-only. |
| `add_redeemable_centers[].id` | Yes | `019ed45d-d6c4-7534-830e-501019fd98dd` | Active center already in the parent’s redeemable centers. |

```json
{
  "add_redeemable_centers": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
    }
  ]
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01a162ff-1000-7000-8000-000000000001",
    "redeemable_centers": [
      {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ]
  }
}
```

#### Logic

Applies to composite therapy assignments only. Repeated additions do not duplicate selections; omission never removes centers. Rejects cancelled program/service/extension records. Does not validate live catalogue availability or alter session allowance/usage. Existing empty selections remain empty until this action is called. Reload service and list eligibility.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Cannot add centers to a cancelled composite therapy service."
}
```

`400 Bad Request`

```json
{
  "detail": {
    "add_redeemable_centers": "Centers must be active members of the program's redeemable centers."
  }
}
```

### 11. Look up a therapy service by redemption code

Resolve a scanned code to its assigned service occurrence before redemption.

**Method:** `GET`

**URL:** `<baseURL>/programs/therapy-programs/services/`

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `code` | Yes for lookup | `RC123456` | Case-insensitive redemption code; response is still a list. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "01a162ff-1000-7000-8000-000000000001",
      "redeemable_centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
          "code": "C0001",
          "name": "Biopeak Bengaluru"
        }
      ],
      "program": {
        "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
        "uid": "P0123",
        "profile": {
          "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
          "contact_email": "client@example.com",
          "phone": "+91-9876543210",
          "first_name": "Rohan",
          "last_name": "Shah",
          "gender": "Male",
          "date_of_birth": "1990-05-12",
          "image": null,
          "created_at": "2026-10-22T10:00:00+05:30",
          "updated_at": "2026-10-22T10:00:00+05:30",
          "is_main": true,
          "is_legacy": false,
          "is_onboarding_sent": false,
          "is_onboarding_completed": false,
          "is_converted": true
        },
        "program_type": "Composite",
        "notes": "Customer wellness programme",
        "expires_at": "2026-12-31",
        "is_complimentary": true,
        "is_credit": false,
        "price": null,
        "services_count": 3,
        "sessions_cancelled": null,
        "redeemable_centers_count": 1,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "cancelled_date": null,
        "created_date": "2026-10-22",
        "is_active": true,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30",
        "credit_received": null
      },
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
            "name": "Biopeak Bengaluru",
            "image": null,
            "address": "Indiranagar, Bengaluru",
            "address_line_1": "100 Example Road",
            "address_line_2": null,
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560038",
            "staff_count": 4,
            "inactive_staff_count": 0,
            "customer_count": 20,
            "inactive_customer_count": 0,
            "is_active": true,
            "created_at": "2026-10-22T10:00:00+05:30",
            "updated_at": "2026-10-22T10:00:00+05:30"
          }
        ]
      },
      "service_assignment_type": "Standalone",
      "service_assignment_type_code": "standalone",
      "sessions_count": 4,
      "sessions_used": 0,
      "sessions_cancelled": 0,
      "redeem_code": "RC123456",
      "created_date": "2026-10-22",
      "created_at": "2026-10-22T10:00:00+05:30",
      "is_active": true,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null
    }
  ]
}
```

#### Logic

The route name contains therapy-programs, but its lookup queries therapy service extensions and includes composite-owned services. No matching code returns an empty collection. Lookup alone does not enforce redemption eligibility.

### 12. Redeem therapy sessions

Consume one session or all remaining sessions for the assigned therapy service.

**Method:** `POST`

**URL:** `<baseURL>/services/therapy-services/<program_service_id>/redeem/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000001` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `center_id` | Yes | `019ed45d-d6c4-7534-830e-501019fd98dd` | Requested redemption center. |
| `redemption_type` | No | `single` | single (default) or all. |
| `redeemed_date` | No | `2026-10-22` | Defaults to current local date. |

```json
{
  "center_id": "019ed45d-d6c4-7534-830e-501019fd98dd",
  "redemption_type": "single",
  "redeemed_date": "2026-10-22"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01a162ff-1000-7000-8000-000000000001",
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
          "name": "Biopeak Bengaluru",
          "image": null,
          "address": "Indiranagar, Bengaluru",
          "address_line_1": "100 Example Road",
          "address_line_2": null,
          "city": "Bengaluru",
          "state": "Karnataka",
          "country": "India",
          "pincode": "560038",
          "staff_count": 4,
          "inactive_staff_count": 0,
          "customer_count": 20,
          "inactive_customer_count": 0,
          "is_active": true,
          "created_at": "2026-10-22T10:00:00+05:30",
          "updated_at": "2026-10-22T10:00:00+05:30"
        }
      ]
    },
    "sessions_count": 4,
    "sessions_used": 1,
    "sessions_cancelled": 0,
    "created_at": "2026-10-22T10:00:00+05:30",
    "redeemed_date": "2026-10-22"
  }
}
```

#### Logic

This action path uses the assigned program-service id despite its /services/ prefix. For all, send the same body with redemption_type=all; the response shows sessions_used=sessions_count. Requires active composite/line/therapy/catalogue records, non-expired parent, remaining sessions, active selected center at both entitlement levels, and an active service-center assignment. Availability is checked here, not at assignment. Existing open-appointment protections remain in place. Reload detail, lists and redemption history.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "center_id": [
      "This program service is not redeemable or available at this center."
    ]
  }
}
```

`400 Bad Request`

```json
{
  "detail": "No sessions remaining for this service."
}
```

### 13. Retrieve therapy redemption history

Show persisted session consumption and cancellation entries.

**Method:** `GET`

**URL:** `<baseURL>/services/therapy-services/<program_service_id>/redemption-history/`

**Access:** Admin or associate; customers may read history for their own therapy services.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000001` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000011",
      "redemption_type": "Redeem",
      "redeem_center": {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      },
      "redeemed_date": "2026-10-22",
      "redeemed_at": "2026-10-22T10:00:00+05:30",
      "quantity": 1,
      "redeemed_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "appointment": null
    }
  ]
}
```

#### Logic

Sorted by redeemed_date and redeemed_at descending. Composite cancellations also create Cancel history for unused sessions. Session cancellation does not increase sessions_used.

### 14. Cancel an assigned therapy service

Cancel the service’s unused allowance while preserving its history.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/therapy-services/<program_service_id>/cancel/`

**Access:** Admin or associate; X-Center-ID required and must identify an existing center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000001` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `cancellation_reason` | No | `Customer request` | Text, blank or null. |
| `cancelled_date` | No | `2026-10-22` | Defaults to current local date. |

```json
{
  "cancellation_reason": "Customer request",
  "cancelled_date": "2026-10-22"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Customer request",
    "cancelled_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "cancelled_at": "2026-10-22T10:00:00+05:30",
    "cancelled_date": "2026-10-22"
  }
}
```

#### Logic

Rejects already cancelled or fully used services. Marks the line inactive, records remaining allowance in sessions_cancelled and adds Cancel redemption history for composite therapy. Reload the service and redemption history.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Program service is already cancelled."
}
```

`400 Bad Request`

```json
{
  "detail": "Service cannot be cancelled since it is already used"
}
```

### 15. Retrieve an individual assessment service

Open the assigned assessment occurrence and its current result/document counters.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "01a162ff-1000-7000-8000-000000000002",
    "service": {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac9",
      "name": "Health Assessment",
      "service_category": "Assessment",
      "service_category_code": "assessment",
      "image": null,
      "centers": null
    },
    "data": {},
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "fetch_count": 0,
    "fetch_results_count": 0,
    "fetch_documents_count": 0,
    "fetch_pending_count": 0,
    "created_date": "2026-10-22",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

#### Logic

Use the assigned assessment id, not service.id. This detail has no PATCH method; assessment edits use the dedicated request/result operations below. Assessment occurrences have no therapy session counters.

### 16. List providers for an assessment

Discover available providers and their configured fetch, booking and confirmation input keys.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/providers/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001",
      "is_api_enabled": true,
      "fetch_fields": [
        "kit_id"
      ],
      "fetch_profile_fields": [
        "full_name"
      ],
      "booking_fields": [
        "kit_id"
      ],
      "booking_profile_fields": [
        "full_name"
      ],
      "confirm_order_fields": [],
      "confirm_order_file_fields": []
    }
  ]
}
```

#### Logic

The assessment line must be active. Providers must be active and have an active product/service assignment. Input arrays are provider configuration, not fixed fields guaranteed for every provider. Their values may be empty or null for booking/confirmation configuration.

### 17. List products for the assessment

Select a product assigned to this service before ordering, fetching or creating results.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/products/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `provider` | No | `PRV0001` | Provider code, not provider UUID. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    }
  ]
}
```

#### Logic

Requires an active assessment line, product, provider and product/service assignment. Base product output contains only id, name and code.

### 18. Retrieve allowed result document types

Populate the manual-result document type selector for the chosen product.

**Method:** `GET`

**URL:** `<baseURL>/products/<product_id>/allowed-documents/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `product_id` | Yes | `019f1000-0000-7000-8000-000000000001` | Catalogue product UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Allowed document types retrieved.",
  "data": [
    {
      "display_name": "Bugspeaks Report",
      "value": "bugspeaks_report"
    }
  ]
}
```

#### Logic

This is an unpaginated list. Use value, not display_name, in document_type. Values depend on provider/product callback configuration.

### 19. Create an assessment report order

Save provider booking inputs as a pending order before confirmation.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/request-report/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `product_id` | Yes | `019f1000-0000-7000-8000-000000000001` | Active product assigned to this service. |
| `data` | Conditional | `{"kit_id":"KIT-123"}` | Object containing every configured provider booking_fields key; defaults to {}. |
| `profile_data` | Conditional | `{"full_name":"Rohan Shah"}` | Object containing configured booking_profile_fields keys; defaults to {}. |

```json
{
  "product_id": "019f1000-0000-7000-8000-000000000001",
  "data": {
    "kit_id": "KIT-123"
  },
  "profile_data": {
    "full_name": "Rohan Shah"
  }
}
```

#### Response — `201 Created`

```json
{
  "detail": "Report request accepted.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "status": "Pending",
    "status_code": "pending",
    "request_type": "Order",
    "request_type_code": "order",
    "is_submitted": false,
    "attempts_count": 0,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Example represents a configured Gut Microbiome provider. Actual keys come from request 16; unknown keys are discarded and missing configured keys return 400. Only products with an implemented report-request handler can be ordered. This creates a pending, unsubmitted order; call confirmation after reviewing it.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "product_id": "An active product and program service are required."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "product_id": "Report requesting is not supported for this product."
  }
}
```

### 20. List assessment result requests

Show pending orders, fetch jobs, statuses, results and available request edits.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/result-requests/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `mode` | No | `order` | fetch or order. |
| `status` | No | `pending` | queued, running, submitted, pending, completed, partially_fetched, failed or cancelled. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000005",
      "provider": {
        "id": "019f1000-0000-7000-8000-000000000002",
        "name": "Example Provider",
        "code": "PRV0001"
      },
      "product": {
        "id": "019f1000-0000-7000-8000-000000000001",
        "name": "Gut Microbiome",
        "code": "PROD0001"
      },
      "data": {
        "kit_id": "KIT-123"
      },
      "profile_data": {
        "full_name": "Rohan Shah"
      },
      "files": [],
      "provider_lifecycle": null,
      "status": "Pending",
      "status_code": "pending",
      "request_type": "Order",
      "request_type_code": "order",
      "is_submitted": false,
      "attempts_count": 0,
      "failure_detail": "",
      "started_at": null,
      "completed_at": null,
      "results": [],
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Newest first. files previews at most three files; retrieve its files endpoint for all. provider_lifecycle is null when no provider lifecycle handler applies; supported providers return their provider-specific lifecycle object. Refetch/confirmation execute asynchronously, so reload this list or detail to observe the saved status. For the currently integrated Bugspeaks and Strand lifecycle handlers, a populated provider_lifecycle has event and received_at fields; for example {"event":"<provider-event>","received_at":"2026-10-22T10:00:00+05:30"}.

### 21. Fetch existing provider results

Create a provider fetch request without creating a new report order.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/result-requests/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `provider_id` | Yes | `019f1000-0000-7000-8000-000000000002` | Active provider UUID with enabled/active API. |
| `product_id` | Yes | `019f1000-0000-7000-8000-000000000001` | Active product assigned to this service and provider. |
| `data` | Yes | `{"kit_id":"KIT-123"}` | Object matching provider fetch_fields. |
| `profile_data` | Yes | `{"full_name":"Rohan Shah"}` | Object matching provider fetch_profile_fields. |

```json
{
  "provider_id": "019f1000-0000-7000-8000-000000000002",
  "product_id": "019f1000-0000-7000-8000-000000000001",
  "data": {
    "kit_id": "KIT-123"
  },
  "profile_data": {
    "full_name": "Rohan Shah"
  }
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "provider": {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001"
    },
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "status": "Queued",
    "status_code": "queued",
    "request_type": "Fetch",
    "request_type_code": "fetch",
    "attempts_count": 0,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "results": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Requires an active assessment and a registered fetch handler. data/profile_data are write-only in this POST response; the GET request-history response includes their saved values. Worker timing can change status; reload request detail.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "product_id": "This product is not available for result fetching."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "product_id": "Result fetching is not supported for this product."
  }
}
```

### 22. Retrieve an individual result request

Inspect one order/fetch request and its saved provider inputs.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "provider": {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001"
    },
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "data": {
      "kit_id": "KIT-123"
    },
    "profile_data": {
      "full_name": "Rohan Shah"
    },
    "files": [],
    "provider_lifecycle": null,
    "status": "Pending",
    "status_code": "pending",
    "request_type": "Order",
    "request_type_code": "order",
    "is_submitted": false,
    "attempts_count": 0,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "results": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Use the outer result-request id from request 19, 20 or 21. Do not substitute the result id or product id. provider_lifecycle is provider-specific and nullable.

### 23. Edit a pending report order

Correct booking/profile inputs before submitting an order.

**Method:** `PATCH`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `data` | No | `{"kit_id":"KIT-456"}` | Provider booking-fields object. |
| `profile_data` | No | `{"full_name":"Rohan Shah"}` | Provider booking-profile-fields object. |

```json
{
  "data": {
    "kit_id": "KIT-456"
  },
  "profile_data": {
    "full_name": "Rohan Shah"
  }
}
```

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "provider": {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001"
    },
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "data": {
      "kit_id": "KIT-456"
    },
    "profile_data": {
      "full_name": "Rohan Shah"
    },
    "files": [],
    "provider_lifecycle": null,
    "status": "Pending",
    "status_code": "pending",
    "request_type": "Order",
    "request_type_code": "order",
    "is_submitted": false,
    "attempts_count": 0,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "results": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Only unsubmitted pending order requests may be edited. Fetch requests, non-pending orders and submitted orders are rejected. Omitted objects retain their stored values; supplied objects must contain all configured keys. Provider-specific storage wrapping remains server-owned.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Only orders can be edited."
}
```

`400 Bad Request`

```json
{
  "detail": "Only pending orders can be edited."
}
```

`400 Bad Request`

```json
{
  "detail": "Submitted orders cannot be edited."
}
```

### 24. Confirm a report order

Validate confirmation inputs and queue provider submission.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/confirm-order/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `confirm_fields` | Conditional | `{}` | Object containing configured confirm_order_fields; defaults to {}. |
| `confirm_files` | Conditional | `{}` | Map of actual uploaded files using configured confirm_order_file_fields; defaults to {}. |

```json
{
  "confirm_fields": {},
  "confirm_files": {}
}
```

#### Response — `202 Accepted`

```json
{
  "detail": "Order confirmation accepted."
}
```

#### Logic

The empty example applies only when the selected provider’s confirmation configuration requires no extra values. Provider handlers additionally validate saved booking data; for example Gut Microbiome confirmation needs a nonempty saved kit_id. Strand needs sample_collection_date in confirm_fields and consent_file in confirm_files. Use multipart/form-data for files (for example confirm_files.consent_file) and a JSON-encoded confirm_fields part. Already submitted/queued/running requests return 202 without resubmitting. Only supported pending orders (and the implemented provider-specific failed-order retry) can be submitted.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Only non-cancelled order requests can be confirmed."
}
```

`400 Bad Request`

```json
{
  "detail": "A failed booking cannot be submitted again. Create another order."
}
```

### 25. List every request attachment

Retrieve request files omitted from the three-file preview.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/files/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000012",
      "field_name": "consent_file",
      "file": "https://files.example.com/consent.pdf",
      "filename": "consent.pdf",
      "content_type": "application/pdf",
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Files are newest first. Use returned file URLs to retrieve the uploaded content; these are request attachments, separate from service result documents.

### 26. Refetch a result request

Requeue a supported submitted order or fetch job to retrieve current provider results.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/refetch/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `—` | No | `{}` | No writable client fields; send an empty object. |

```json
{}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "provider": {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001"
    },
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "data": {
      "kit_id": "KIT-123"
    },
    "status": "Queued",
    "status_code": "queued",
    "request_type": "Order",
    "request_type_code": "order",
    "is_submitted": true,
    "attempts_count": 1,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "results": [],
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

This operation deletes the request’s existing result records and their documents before requeuing retrieval. Unsubmitted orders must be confirmed first; cancelled orders cannot be refetched. Current active service/product/provider/API and a matching handler are required. Reload request, results, documents and parent counters.

#### Errors

`400 Bad Request`

```json
{
  "detail": "An unsubmitted order cannot be refetched. Confirm it first."
}
```

`400 Bad Request`

```json
{
  "detail": "A cancelled order request cannot be refetched."
}
```

### 27. Cancel a result request

Mark an unfinished request cancelled.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/result-requests/<request_id>/cancel/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `request_id` | Yes | `019f1000-0000-7000-8000-000000000005` | ResultRequest UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `—` | No | `{}` | No writable client fields; send an empty object. |

```json
{}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000005",
    "provider": {
      "id": "019f1000-0000-7000-8000-000000000002",
      "name": "Example Provider",
      "code": "PRV0001"
    },
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "data": {
      "kit_id": "KIT-123"
    },
    "status": "Cancelled",
    "status_code": "cancelled",
    "request_type": "Order",
    "request_type_code": "order",
    "is_submitted": true,
    "attempts_count": 1,
    "failure_detail": "",
    "started_at": null,
    "completed_at": null,
    "results": [],
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Rejects completed or already cancelled requests. This changes the local request state; do not assume a provider-side order cancellation is performed.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Result request is already cancelled."
}
```

`400 Bad Request`

```json
{
  "detail": "A completed result request cannot be cancelled."
}
```

### 28. List assessment results

Retrieve manually uploaded and provider-created result records for the assigned assessment.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/results/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `product` | No | `019f1000-0000-7000-8000-000000000001` | Product UUID. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000003",
      "product": {
        "id": "019f1000-0000-7000-8000-000000000001",
        "name": "Gut Microbiome",
        "code": "PROD0001"
      },
      "provider_name": "Example Provider",
      "product_name": "Gut Microbiome",
      "result_mode": "Upload",
      "result_mode_code": "upload",
      "document_type": "Bugspeaks Report",
      "document_type_code": "bugspeaks_report",
      "sample_collection_date": "2026-10-20",
      "report_generation_date": "2026-10-22",
      "documents_count": 0,
      "documents": [],
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Newest first. documents is a preview of at most three documents; use the result-documents endpoint for the complete collection. result_mode distinguishes upload/fetch/order with a corresponding result_mode_code.

### 29. Create a manual assessment result

Create result metadata before uploading a document.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/results/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `product_id` | Yes | `019f1000-0000-7000-8000-000000000001` | Active product assigned to the assessment service. |
| `document_type` | Yes | `bugspeaks_report` | Value from the product’s allowed-documents response. |
| `sample_collection_date` | No | `2026-10-20` | Date or null. |
| `report_generation_date` | No | `2026-10-22` | Date or null. |

```json
{
  "product_id": "019f1000-0000-7000-8000-000000000001",
  "document_type": "bugspeaks_report",
  "sample_collection_date": "2026-10-20",
  "report_generation_date": "2026-10-22"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000003",
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "provider_name": "Example Provider",
    "product_name": "Gut Microbiome",
    "result_mode": "Upload",
    "result_mode_code": "upload",
    "document_type": "Bugspeaks Report",
    "document_type_code": "bugspeaks_report",
    "sample_collection_date": "2026-10-20",
    "report_generation_date": "2026-10-22",
    "documents_count": 0,
    "documents": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

The assessment line must be active. The server derives provider_name/product_name and sets result_mode=upload. A result record alone contains no uploaded file; call request 35 next. Refresh assessment and composite counters.

#### Errors

`400 Bad Request`

```json
{
  "detail": "An inactive program service cannot receive results."
}
```

`400 Bad Request`

```json
{
  "detail": {
    "product_id": "This product is not available for the service."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "document_type": "This document type is not allowed for the selected product."
  }
}
```

### 30. Retrieve an individual assessment result

Read one result and its document preview.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/results/<result_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result_id` | Yes | `019f1000-0000-7000-8000-000000000003` | ServiceResult UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000003",
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "provider_name": "Example Provider",
    "product_name": "Gut Microbiome",
    "result_mode": "Upload",
    "result_mode_code": "upload",
    "document_type": "Bugspeaks Report",
    "document_type_code": "bugspeaks_report",
    "sample_collection_date": "2026-10-20",
    "report_generation_date": "2026-10-22",
    "documents_count": 0,
    "documents": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Use the result id returned by result creation/listing; the assigned program-service id is a different resource.

### 31. Edit assessment result dates

Correct collection or report dates on an existing result.

**Method:** `PATCH`

**URL:** `<baseURL>/programs/program-services/results/<result_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result_id` | Yes | `019f1000-0000-7000-8000-000000000003` | ServiceResult UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `sample_collection_date` | No | `2026-10-21` | Date or null. |
| `report_generation_date` | No | `2026-10-22` | Date or null. |
| `product_id` | No | `019f1000-0000-7000-8000-000000000001` | Accepted but discarded during update; cannot change the result product. |
| `document_type` | No | `bugspeaks_report` | Accepted/choice-validated but discarded during update. |

```json
{
  "sample_collection_date": "2026-10-21",
  "report_generation_date": "2026-10-22"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000003",
    "product": {
      "id": "019f1000-0000-7000-8000-000000000001",
      "name": "Gut Microbiome",
      "code": "PROD0001"
    },
    "provider_name": "Example Provider",
    "product_name": "Gut Microbiome",
    "result_mode": "Upload",
    "result_mode_code": "upload",
    "document_type": "Bugspeaks Report",
    "document_type_code": "bugspeaks_report",
    "sample_collection_date": "2026-10-21",
    "report_generation_date": "2026-10-22",
    "documents_count": 0,
    "documents": [],
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

This PATCH effectively edits dates only. Provider/product metadata, document type, result mode and ownership remain server-controlled.

### 32. Delete an assessment result

Remove a result and its attached documents.

**Method:** `DELETE`

**URL:** `<baseURL>/programs/program-services/results/<result_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result_id` | Yes | `019f1000-0000-7000-8000-000000000003` | ServiceResult UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Deleted successfully."
}
```

#### Logic

Deletion cascades to result documents and updates result/document/fetch counters on the service and composite. Stored file deletion is scheduled after commit. Refresh results, documents, assessment detail and composite detail.

### 33. List every document for an assessment service

Show the complete document collection across the service’s results.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/documents/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result` | No | `019f1000-0000-7000-8000-000000000003` | Result UUID. |
| `document_type` | No | `bugspeaks_report` | Exact result document-type code. |
| `document_category` | No | `report` | report or raw. |
| `module_category` | No | `functional_metabolic_tests` | Derived module category code. |
| `search` | No | `report` | Filename substring, case-insensitive. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000004",
      "file": "https://files.example.com/report.pdf",
      "filename": "report.pdf",
      "content_type": "application/pdf",
      "document_category": "Report file",
      "document_category_code": "report",
      "module_category": "Functional & Metabolic Tests",
      "module_category_code": "functional_metabolic_tests",
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

#### Logic

Document type and module category belong to the parent result; file category belongs to the individual document. Use document.id for deletion and file for downloading.

### 34. List every document for a result

Retrieve documents omitted from the result’s three-document preview.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/results/<result_id>/documents/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result_id` | Yes | `019f1000-0000-7000-8000-000000000003` | ServiceResult UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_type` | No | `bugspeaks_report` | Exact parent result document-type code. |
| `document_category` | No | `report` | report or raw. |
| `search` | No | `report` | Filename substring, case-insensitive. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000004",
      "file": "https://files.example.com/report.pdf",
      "filename": "report.pdf",
      "content_type": "application/pdf",
      "document_category": "Report file",
      "document_category_code": "report",
      "module_category": "Functional & Metabolic Tests",
      "module_category_code": "functional_metabolic_tests",
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    }
  ]
}
```

### 35. Upload an assessment result document

Attach an actual report/raw file to the existing result.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/results/<result_id>/documents/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `result_id` | Yes | `019f1000-0000-7000-8000-000000000003` | ServiceResult UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `file` | Yes | `<binary report.pdf>` | Actual uploaded file; use multipart/form-data. |
| `document_category` | Yes | `report` | report or raw. |

The JSON below illustrates form-part names and values. Send file as a binary multipart part, not as a JSON filename or a base64 string.

```json
{
  "file": "<binary report.pdf>",
  "document_category": "report"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "019f1000-0000-7000-8000-000000000004",
    "file": "https://files.example.com/report.pdf",
    "filename": "report.pdf",
    "content_type": "application/pdf",
    "document_category": "Report file",
    "document_category_code": "report",
    "module_category": "Functional & Metabolic Tests",
    "module_category_code": "functional_metabolic_tests",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30"
  }
}
```

#### Logic

Both result and assessment service must be active. Server computes filename, content_type, file hash and module category. Refresh result, service and composite counters.

#### Errors

`400 Bad Request`

```json
{
  "detail": "An inactive program service cannot receive documents."
}
```

`400 Bad Request`

```json
{
  "detail": "An inactive result cannot receive documents."
}
```

### 36. Delete an individual assessment document

Remove one file without deleting the result metadata.

**Method:** `DELETE`

**URL:** `<baseURL>/programs/program-result-documents/<document_id>/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `document_id` | Yes | `019f1000-0000-7000-8000-000000000004` | ServiceDocument UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Deleted successfully."
}
```

#### Logic

Updates result/service/composite document counters and schedules stored-file removal after commit. Refresh documents and affected counters.

### 37. Cancel an assigned assessment service

Deactivate one assessment occurrence.

**Method:** `POST`

**URL:** `<baseURL>/programs/program-services/assessment-services/<program_service_id>/cancel/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000002` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `cancellation_reason` | No | `Customer request` | Text, blank or null. |
| `cancelled_date` | No | `2026-10-22` | Defaults to current local date. |

```json
{
  "cancellation_reason": "Customer request",
  "cancelled_date": "2026-10-22"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "cancellation_reason": "Customer request",
    "cancelled_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "cancelled_at": "2026-10-22T10:00:00+05:30",
    "cancelled_date": "2026-10-22"
  }
}
```

#### Logic

Rejects an already cancelled line. Assessment cancellation uses the shared program-service cancellation flow and does not burn therapy sessions. Existing results/documents are not automatically deleted. Reload detail and lists.

#### Errors

`400 Bad Request`

```json
{
  "detail": "Program service is already cancelled."
}
```

### 38. Retrieve an individual consultation service

Read the assigned consultation’s parent program, catalogue service and lifecycle metadata.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/consultation-services/<program_service_id>/`

**Access:** Staff only. Admin or associate with active X-Center-ID assignment; associate must access the composite at its owning or redeemable center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_service_id` | Yes | `01a162ff-1000-7000-8000-000000000003` | Assigned ProgramService UUID, not catalogue Service UUID. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "01a162ff-1000-7000-8000-000000000003",
    "program": {
      "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
      "uid": "P0123",
      "profile": {
        "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
        "contact_email": "client@example.com",
        "phone": "+91-9876543210",
        "first_name": "Rohan",
        "last_name": "Shah",
        "gender": "Male",
        "date_of_birth": "1990-05-12",
        "image": null,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30",
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": true
      },
      "program_type": "Composite",
      "notes": "Customer wellness programme",
      "expires_at": "2026-12-31",
      "is_complimentary": true,
      "is_credit": false,
      "price": null,
      "services_count": 3,
      "sessions_cancelled": null,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "cancelled_date": null,
      "created_date": "2026-10-22",
      "is_active": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "service": {
      "id": "019e1622-403b-74d1-a991-df3b388b4aca",
      "name": "Doctor Consultation",
      "service_category": "Consultation",
      "service_category_code": "consultation",
      "image": null,
      "centers": null
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "is_active": true,
    "created_date": "2026-10-22",
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    },
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null
  }
}
```

#### Logic

Requires a consultation catalogue category and an existing ConsultationProgramService extension on a composite parent. Wrong-category, unrelated or inaccessible IDs return 404. No consultation PATCH, session allowance, booking or redemption is introduced by this flow. Use category=consultation on either composite-service list for list access.

### 39. Retrieve profile centers for center selection

Resolve center UUIDs and names when selecting parent and per-service redemption centers.

**Method:** `GET`

**URL:** `<baseURL>/profiles/<profile_id>/centers/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019e20ea-5d4d-7356-b759-21546cfd8695` | Customer profile UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `search` | No | `Bengaluru` | Center name prefix/substring. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000013",
      "center": {
        "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
        "code": "C0001",
        "name": "Biopeak Bengaluru",
        "image": null,
        "address": "Indiranagar, Bengaluru",
        "address_line_1": "100 Example Road",
        "address_line_2": null,
        "city": "Bengaluru",
        "state": "Karnataka",
        "country": "India",
        "pincode": "560038",
        "staff_count": 4,
        "inactive_staff_count": 0,
        "customer_count": 20,
        "inactive_customer_count": 0,
        "is_active": true,
        "created_at": "2026-10-22T10:00:00+05:30",
        "updated_at": "2026-10-22T10:00:00+05:30"
      },
      "is_primary": true,
      "created_at": "2026-10-22T10:00:00+05:30",
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      }
    }
  ]
}
```

#### Logic

Use center.id, not the assignment’s outer id. This endpoint does not implement active filtering. Assignment/center-addition APIs perform authoritative active/member validation. The composite’s current parent center response exposes code/name; match the unique center code to this lookup if the selected UUIDs were not retained.

### 40. Retrieve template services before assignment

Read active template categories, therapy quantities and the catalogue IDs needed for per-service center selections.

**Method:** `GET`

**URL:** `<baseURL>/programs/composites/templates/<template_id>/services/`

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `template_id` | Yes | `01a162da-baad-773a-92af-b93a3138d3f4` | Composite template UUID. |

#### Query Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category` | No | `therapy` | Single assessment, therapy or consultation value. |
| `search` | No | `Recovery` | Catalogue service-name prefix/substring. |
| `page` | No | `1` | Page number. |
| `limit` | No | `10` | Maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "019f1000-0000-7000-8000-000000000014",
      "name": "Recovery Therapy",
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
            "name": "Biopeak Bengaluru",
            "image": null,
            "address": "Indiranagar, Bengaluru",
            "address_line_1": "100 Example Road",
            "address_line_2": null,
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560038",
            "staff_count": 4,
            "inactive_staff_count": 0,
            "customer_count": 20,
            "inactive_customer_count": 0,
            "is_active": true,
            "created_at": "2026-10-22T10:00:00+05:30",
            "updated_at": "2026-10-22T10:00:00+05:30"
          }
        ]
      },
      "quantity": 4,
      "is_global": false,
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "is_active": true,
      "is_locked": true,
      "centers_count": 1,
      "redeemable_centers_count": 1,
      "products": [],
      "products_count": 0,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30",
      "created_by": {
        "id": "019f1000-0000-7000-8000-000000000006",
        "email": "staff@example.com",
        "first_name": "Asha",
        "last_name": "Rao",
        "image": null,
        "last_login": "2026-10-22T10:00:00+05:30"
      },
      "prerequisite": null
    }
  ]
}
```

#### Logic

Outer id is a template-service line ID. Use nested service.id in therapy_service_centers[].id; do not submit the template line ID. Assignment copies only active template lines whose catalogue services are active. Therapy quantity supplies initial sessions_count. Do not derive assignment eligibility from the catalogue center previews.

### 41. Assign a composite through the profile route

Create the composite with explicit therapy redemption-center selections.

**Method:** `POST`

**URL:** `<baseURL>/profiles/<profile_id>/programs/composite-programs/`

**Access:** Admin or associate with X-Center-ID. Profile must belong to the center; associates must also be assigned to that profile at the center.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019e20ea-5d4d-7356-b759-21546cfd8695` | Customer profile UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `composite_template_id` | Yes | `01a162da-baad-773a-92af-b93a3138d3f4` | Active template with at least one active service. |
| `name` | No | `Wellness Programme` | Text, blank or null; blank becomes null. |
| `assessment_type` | Conditional | `baseline` | Required when active template services include assessment; baseline, annual, six_month_review, retest or special_investigation. |
| `notes` | No | `Customer wellness programme` | Text, blank or null. |
| `expires_at` | No | `2026-12-31` | Optional date; non-null date cannot precede today. |
| `is_complimentary` | No | `true` | Defaults to true. |
| `price` | Conditional | `12000.00` | Required when not complimentary; decimal string or null. |
| `redeemable_centers` | Yes | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Nonempty active centers assigned to the customer profile. |
| `redeemable_centers[].id` | Yes | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID. |
| `therapy_service_centers` | Conditional | `Array` | Exactly one entry for each active therapy catalogue service; omit/[] when none exist. |
| `therapy_service_centers[].id` | Yes per entry | `019e1622-403b-74d1-a991-df3b388b4ac8` | Nested service.id from template-services response. |
| `therapy_service_centers[].centers` | Yes per entry | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Nonempty {id} reference subset of selected parent centers. |
| `therapy_service_centers[].centers[].id` | Yes per center | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID; use the existing {id} reference pattern. |
| `created_date` | No | `2026-10-22` | Defaults to current local date. |

```json
{
  "composite_template_id": "01a162da-baad-773a-92af-b93a3138d3f4",
  "name": "Wellness Programme",
  "assessment_type": "baseline",
  "notes": "Customer wellness programme",
  "expires_at": "2026-12-31",
  "is_complimentary": true,
  "redeemable_centers": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
    }
  ],
  "therapy_service_centers": [
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
        }
      ]
    }
  ]
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
    "uid": "P0123",
    "name": "Wellness Programme",
    "assessment_type": "Baseline",
    "assessment_type_code": "baseline",
    "profile": {
      "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
      "first_name": "Rohan",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-05-12",
      "image": null,
      "home_center": null,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "center": {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    },
    "composite_template": {
      "id": "01a162da-baad-773a-92af-b93a3138d3f4",
      "code": "CMP0001",
      "name": "Wellness Programme",
      "is_active": true
    },
    "program_type": "composite",
    "notes": "Customer wellness programme",
    "expires_at": "2026-12-31",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": null,
    "services_count": 3,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 1,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-22",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    }
  }
}
```

#### Logic

No catalogue service-availability validation runs at assignment. Every therapy template quantity must be positive. One ProgramService and matching category extension are created per active template line; therapy receives its quantity as sessions_count. Assessment and consultation have no session counters. Stored service centers are required even when the service is currently unavailable. This create response does not preload service_preview; retrieve the newly created composite and full services.

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "therapy_service_centers": "Select redemption centers for every active therapy service in the template."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "therapy_service_centers": "Duplicate therapy service selections are not allowed."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "therapy_service_centers": "Select only active therapy services from this template."
  }
}
```

`400 Bad Request`

```json
{
  "detail": {
    "therapy_service_centers": "Centers must be active members of the program's redeemable centers."
  }
}
```

### 42. Assign a composite through the center route

Create the same category-specific assignments from a center-scoped customer selection.

**Method:** `POST`

**URL:** `<baseURL>/centers/<center_id>/composite-programs/`

**Access:** Admin or associate with PackagesPermission. For associates, X-Center-ID must match the path center and the associate must be assigned there.

#### Path Parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `center_id` | Yes | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `019e20ea-5d4d-7356-b759-21546cfd8695` | Active profile assigned to the path center. |
| `composite_template_id` | Yes | `01a162da-baad-773a-92af-b93a3138d3f4` | Active template. |
| `name` | No | `Wellness Programme` | Text, blank or null. |
| `assessment_type` | Conditional | `baseline` | Required for templates containing assessment; same choices as profile assignment. |
| `notes` | No | `Customer wellness programme` | Text, blank or null. |
| `expires_at` | Yes | `2026-12-31` | Date on or after today. |
| `is_complimentary` | No | `true` | Defaults to true. |
| `price` | Conditional | `12000.00` | Required when not complimentary; decimal string or null. |
| `redeemable_centers` | Yes | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Nonempty active centers assigned to the profile. |
| `redeemable_centers[].id` | Yes | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID. |
| `therapy_service_centers` | Conditional | `Array` | One entry for every active therapy service. |
| `therapy_service_centers[].id` | Yes per entry | `019e1622-403b-74d1-a991-df3b388b4ac8` | Catalogue service UUID. |
| `therapy_service_centers[].centers` | Yes per entry | `[{"id":"019ed45d-d6c4-7534-830e-501019fd98dd"}]` | Nonempty active parent-center subset. |
| `therapy_service_centers[].centers[].id` | Yes per center | `019ed45d-d6c4-7534-830e-501019fd98dd` | Center UUID; use the existing {id} reference pattern. |
| `created_date` | No | `2026-10-22` | Defaults to current local date. |

```json
{
  "profile_id": "019e20ea-5d4d-7356-b759-21546cfd8695",
  "composite_template_id": "01a162da-baad-773a-92af-b93a3138d3f4",
  "name": "Wellness Programme",
  "assessment_type": "baseline",
  "expires_at": "2026-12-31",
  "is_complimentary": true,
  "redeemable_centers": [
    {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
    }
  ],
  "therapy_service_centers": [
    {
      "id": "019e1622-403b-74d1-a991-df3b388b4ac8",
      "centers": [
        {
          "id": "019ed45d-d6c4-7534-830e-501019fd98dd"
        }
      ]
    }
  ],
  "notes": "Customer wellness programme"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "id": "01a162fe-2739-7663-b059-fdb6d37f9a16",
    "uid": "P0123",
    "name": "Wellness Programme",
    "assessment_type": "Baseline",
    "assessment_type_code": "baseline",
    "profile": {
      "id": "019e20ea-5d4d-7356-b759-21546cfd8695",
      "contact_email": "client@example.com",
      "phone": "+91-9876543210",
      "first_name": "Rohan",
      "last_name": "Shah",
      "gender": "Male",
      "date_of_birth": "1990-05-12",
      "image": null,
      "home_center": null,
      "created_at": "2026-10-22T10:00:00+05:30",
      "updated_at": "2026-10-22T10:00:00+05:30"
    },
    "center": {
      "id": "019ed45d-d6c4-7534-830e-501019fd98dd",
      "code": "C0001",
      "name": "Biopeak Bengaluru"
    },
    "composite_template": {
      "id": "01a162da-baad-773a-92af-b93a3138d3f4",
      "code": "CMP0001",
      "name": "Wellness Programme",
      "is_active": true
    },
    "program_type": "composite",
    "notes": "Customer wellness programme",
    "expires_at": "2026-12-31",
    "is_complimentary": true,
    "price": null,
    "redeemable_centers": [
      {
        "code": "C0001",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "services": null,
    "services_count": 3,
    "add_ons_count": 0,
    "assessment_services_count": 1,
    "therapy_services_count": 1,
    "consultation_services_count": 1,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "created_date": "2026-10-22",
    "is_active": true,
    "created_at": "2026-10-22T10:00:00+05:30",
    "updated_at": "2026-10-22T10:00:00+05:30",
    "created_by": {
      "id": "019f1000-0000-7000-8000-000000000006",
      "email": "staff@example.com",
      "first_name": "Asha",
      "last_name": "Rao",
      "image": null,
      "last_login": "2026-10-22T10:00:00+05:30"
    }
  }
}
```

#### Logic

Unlike profile assignment, expires_at is required. Per-service center selection and category extension behavior are identical. No service-availability validation runs during creation. Retrieve the created composite before navigating its service operations.


