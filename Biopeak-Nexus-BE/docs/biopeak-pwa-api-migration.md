# Biopeak PWA API migration ePRD

Move PWA authentication and customer operations to Biopeak while keeping report compatibility routes during Phase 2.

`<baseURL>` is the deployed Biopeak API root. `:profile_id` is a Biopeak customer-profile UUID; `:record_id` remains a report record ID; `:program_id` is a Biopeak program UUID; `:service_id` is a program-service UUID, distinct from the catalogue UUID in `service.id`. Do not reuse old profile IDs as Biopeak profile UUIDs.

Send `Authorization: Bearer <Biopeak_access_token>` on authenticated Biopeak requests. APIs 1–3 take their credentials in the payload. Chat APIs 18–20 call `https://ask-ai.biopeak.com/` directly with `X-Api-Token: <token_from_API_16>`. The server-side ASK-AI API key must never be sent by the frontend. Biopeak responses use `detail` and, when present, `data`; there is no `success` property. Paginated lists add `count`, `next` and `previous`. Follow returned pagination links for local lists. Nullable fields and empty collections must be handled.

Customer `email` in API 4 and family-profile responses is the customer's contact email, with no account-email fallback. Profile `phone` is the customer's account phone. These contacts are shared across the customer's family profiles and remain read-only. `age` is derived separately for each profile.

Consumer notices reconcile the frontend team's reported usage with the public contracts below. They are based on static review, without live request or frontend runtime verification.

## Phase: 1

Use Biopeak OTP authentication, retrieve the account and select a Biopeak profile before making profile-scoped requests.

| API | Method | Current URL | New URL |
| --- | --- | --- | --- |
| 1 | POST | `https://api.metsights.com/auth/request-otp/` | `<baseURL>/auth/request-otp/` |
| 2 | POST | `https://api.metsights.com/auth/login-otp/` | `<baseURL>/auth/login-otp/` |
| 3 | POST | `https://api.metsights.com/auth/refresh/` | `<baseURL>/auth/refresh/` |
| 4 | GET | `https://api.metsights.com/users/profile/` | `<baseURL>/customers/account/` |
| 5 | GET | `https://api.metsights.com/profiles/` | `<baseURL>/profiles/` |
| 6 | PATCH | `https://api.metsights.com/profiles/:profile_id/` | `<baseURL>/profiles/:profile_id/` |

### Logical flow

1. **API 1 — Request OTP:** submit the registered phone with login purpose.
2. **API 2 — Login:** submit phone and OTP, then save access and refresh tokens.
3. **API 3 — Refresh:** replace both saved tokens when refreshing.
4. **API 4 — Account:** retrieve account identity and customer contact details.
5. **API 5 — Profiles:** load profiles and retain the selected profile UUID.
6. **API 6 — Update profile:** submit changed writable fields and replace that profile with the returned object.

The customer account endpoint `/customers/account/` is read-only. It does not provide account-profile editing or contact updates.

### API requests

### API 1 — Request OTP

Request a login OTP for a registered phone.

**Method:** `POST`

**URL:** `<baseURL>/auth/request-otp/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `phone` | Yes | `+91-9876543210` | Valid phone with country code; hyphenated and unhyphenated forms are accepted and normalized. |
| `purpose` | No | `"0"` | Default login `"0"`; numeric `0` is accepted. Other choices: `"1"` registration, `"2"` verification. `"login"` is invalid. |

```json
{
  "phone": "+91-9876543210",
  "purpose": "0"
}
```

#### Response — `200 OK`

```json
{
  "detail": "OTP sent successfully."
}
```

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "phone": [
      "Phone number is not registered."
    ]
  }
}
```

**Consumer change:** Change the host and purpose contract. This call returns an acknowledgement, not access/refresh tokens. The frontend's OTP-result wrapper must not require `data`.

### API 2 — OTP login

Authenticate using the registered phone and six-character OTP.

**Method:** `POST`

**URL:** `<baseURL>/auth/login-otp/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `phone` | Yes | `+91-9876543210` | Same normalized phone used for API 1. |
| `otp` | Yes | `123456` | Exactly six characters. |

```json
{
  "phone": "+91-9876543210",
  "otp": "123456"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Login successful.",
  "data": {
    "access": "<Biopeak_access_token>",
    "refresh": "<Biopeak_refresh_token>"
  }
}
```

#### Errors

`400 Bad Request`

```json
{
  "detail": {
    "otp": [
      "OTP is expired or invalid."
    ]
  }
}
```

**Consumer change:** Read `data.access` and `data.refresh`. Customer JWTs contain `user_type: "customer"`, with email/phone claims; replace the frontend's `participant` check. The OTP sequence above does not require the frontend's reported direct-login pre-call.

### API 3 — Refresh tokens

Exchange the refresh token for a new token pair.

**Method:** `POST`

**URL:** `<baseURL>/auth/refresh/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `refresh` | Yes | `<Biopeak_refresh_token>` | Saved refresh token. |

```json
{
  "refresh": "<Biopeak_refresh_token>"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Token refreshed.",
  "data": {
    "access": "<new_access_token>",
    "refresh": "<rotated_refresh_token>"
  }
}
```

**Consumer change:** Use the Biopeak host and saved Biopeak refresh token. Replace both tokens; access lasts one day and refresh lasts 30 days.

### API 4 — Customer account

Retrieve the authenticated account.

**Method:** `GET`

**URL:** `<baseURL>/customers/account/`

Requires a Biopeak customer JWT. No path or query parameters; the account is selected from the authenticated customer.

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<user_uuid>",
    "email": "customer@example.com",
    "phone": "+91-9876543210",
    "date_joined": "<ISO-8601 timestamp>",
    "last_login": null,
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

`email` is the stored customer contact email, including null when absent, with no account-email fallback. It is the same customer-level value returned by APIs 5–6. Phone and last login can also be null. Names, gender, birth date and image belong to individual profiles and are absent from the account response.

**Consumer change:** Use Biopeak JWT. Keep the account `id` separate from profile IDs. Read `email` as customer contact email; email and phone remain read-only.

### API 5 — Customer profiles

List the authenticated customer's selectable profiles.

**Method:** `GET`

**URL:** `<baseURL>/profiles/`

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `active` | No | `1` | `0` inactive, `1` active. Omitted/invalid values do not restrict activity. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<profile_uuid>",
      "email": "customer@example.com",
      "phone": "+91-9876543210",
      "first_name": "Example",
      "last_name": "Customer",
      "gender": "Male",
      "date_of_birth": "1990-01-01",
      "age": 36,
      "image": null,
      "is_main": true,
      "is_onboarding_sent": false,
      "is_onboarding_completed": false,
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>"
    }
  ]
}
```

`email`, `phone`, `age`, names, gender, birth date and image can be null. `age` is completed years from the profile birth date; missing/future birth dates return null. Contact email has no account-email fallback.

**Consumer change:** The new response includes `email`, `phone` and `age`; the earlier reported omissions of these three fields are resolved. Old `uid` and `specialists_count` are absent; onboarding flags are present. Persist the returned Biopeak profile UUID and scope profile caches/requests by it. Contact availability must not determine whether an owned-profile request can run.

#### Selected profile read

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/`

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

**Response — `200 OK`:**

```json
{
  "detail": "Details.",
  "data": {
    "id": "<profile_uuid>",
    "email": "customer@example.com",
    "phone": "+91-9876543210",
    "first_name": "Example",
    "last_name": "Customer",
    "gender": "Male",
    "date_of_birth": "1990-01-01",
    "age": 36,
    "image": null,
    "is_main": true,
    "is_onboarding_sent": false,
    "is_onboarding_completed": false,
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

A missing or unowned profile returns `404 Not Found` with `{"detail":"Customer profile not found."}`.

### API 6 — Update customer profile

Update writable profile fields; return the full updated profile.

**Method:** `PATCH`

**URL:** `<baseURL>/profiles/:profile_id/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `first_name` | No | `Example` | Up to 100 characters; null/blank accepted. |
| `last_name` | No | `Customer` | Up to 100 characters; null/blank accepted. |
| `gender` | No | `"0"` | `"0"` Male, `"1"` Female, `"2"` Other; null/blank accepted. Response uses the display label. |
| `date_of_birth` | No | `1990-01-01` | Date or null; age is recalculated from it. |
| `image` | No | `<uploaded image>` | Multipart image upload; null clears the image. |
| `is_onboarding_sent` | No | `false` | Boolean. |
| `is_onboarding_completed` | No | `false` | Boolean. |

```json
{
  "first_name": "Example",
  "last_name": "Customer",
  "gender": "0",
  "date_of_birth": "1990-01-01"
}
```

**Logic:** `id`, `email`, `phone`, `age`, `is_main`, `created_at` and `updated_at` are read-only. Profile contact updates are not accepted through these fields. A main profile's demographic changes also update the account's demographic fields. Use multipart for image uploads.

#### Response — `200 OK`

```json
{
  "detail": "Updated successfully.",
  "data": {
    "id": "<profile_uuid>",
    "email": "customer@example.com",
    "phone": "+91-9876543210",
    "first_name": "Example",
    "last_name": "Customer",
    "gender": "Male",
    "date_of_birth": "1990-01-01",
    "age": 36,
    "image": null,
    "is_main": true,
    "is_onboarding_sent": false,
    "is_onboarding_completed": false,
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

#### Errors

`404 Not Found`

```json
{
  "detail": "Customer profile not found."
}
```

**Consumer change:** Use the selected Biopeak UUID. Replace profile state with `data`, which includes contact email, phone and age. The old detail's `uid`, `has_pre_assessment`, `specialists`, and `specialists_count` are absent. Set birth date rather than submitting `age`; contact editing stays in the account flow.

## Phase: 2

Move customer operations from phone-based identification to authenticated profile or resource requests. Report-specific operations use the legacy record namespace; record and report lists remain scoped to the selected profile. Obtain chat session credentials through Biopeak and use them with the ASK-AI chat service.

| API | Method | Current URL | New URL |
| --- | --- | --- | --- |
| 7 | GET | `https://api.metsights.com/specialists/` | `<baseURL>/profiles/:profile_id/associates/` |
| 8 | GET | `https://api.metsights.com/records/?code=BIOPEAK_HEALTH` | `<baseURL>/profiles/:profile_id/metsights-legacy/records/` |
| 9 | GET | `https://api.metsights.com/records/:record_id/attachments/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/attachments/` |
| 10 | GET | `https://api.metsights.com/reports/precision-reports/:record_id/consolidated/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/consolidated/` |
| 11 | POST | `https://api.metsights.com/records/:record_id/export-reports/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/export-reports/` |
| 12 | GET | `https://api.metsights.com/reports/biopeak-health-reports/:record_id/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/` |
| 13 | GET | `https://api.metsights.com/reports/biopeak-health-reports/:record_id/trends/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/trends/` |
| 14 | GET | `https://api.metsights.com/reports/biopeak-health-reports/:record_id/files/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/files/` |
| 15 | GET | `https://api.metsights.com/records/:record_id/personalised-plan/` | `<baseURL>/profiles/metsights-legacy/records/:record_id/personalised-plan/` |
| 16 | GET | `https://api.metsights.com/profiles/:profile_id/features/biopeak-chat/` | `<baseURL>/profiles/:profile_id/copilot-chat/` |
| 17 | GET | `https://api.metsights.com/profiles/:profile_id/features/` | `<baseURL>/profiles/:profile_id/features/` |
| 18 | GET | `https://biopeak-ai.metsights.com/chat/history/:session_id/` | `https://ask-ai.biopeak.com/chat/history/:session_id/` |
| 19 | POST | `https://biopeak-ai.metsights.com/chat/stream/:session_id/` | `https://ask-ai.biopeak.com/chat/stream/:session_id/` |
| 20 | POST | `https://biopeak-ai.metsights.com/chat/feedback/:message_id/` | `https://ask-ai.biopeak.com/chat/feedback/:message_id/` |
| 21 | GET | `<baseURL>/external/customer-associates/` | `<baseURL>/profiles/:profile_id/associates/` |
| 22 | GET | `<baseURL>/external/customer-therapy-programs/` | `<baseURL>/profiles/:profile_id/programs/therapy-programs/` |
| 23 | GET | `<baseURL>/external/customer-therapy-programs/summary/` | `<baseURL>/profiles/:profile_id/programs/therapy-programs/summary/` |
| 24 | GET | `<baseURL>/external/customer-therapy-programs/:program_id/` | `<baseURL>/programs/therapy-programs/:program_id/` |
| 25 | GET | `<baseURL>/external/customer-therapy-programs/:program_id/services/` | `<baseURL>/programs/therapy-programs/:program_id/services/` |
| 26 | GET | `<baseURL>/external/customer-therapy-services/:service_id/` | `<baseURL>/programs/program-services/therapy-services/:service_id/` |
| 27 | GET | `<baseURL>/external/customer-therapy-services/:service_id/redemption-history/` | `<baseURL>/services/therapy-services/:service_id/redemption-history/` |
| 28 | GET | `<baseURL>/external/customer-notifications/` | `<baseURL>/notifications/` |
| 29 | GET | `<baseURL>/external/customer-notifications/:notification_id/` | `<baseURL>/notifications/:notification_id/` |
| 30 | POST | `<baseURL>/external/customer-notifications/register/` | `<baseURL>/notifications/register/` |
| 31 | POST | `<baseURL>/external/customer-notifications/deregister/` | `<baseURL>/notifications/deregister/` |
| Additional | GET | `https://api.metsights.com/external/profiles/:profile_id/reports/` | `<baseURL>/profiles/:profile_id/metsights-legacy/reports/` |

### Logical flow

1. **APIs 7–8 — Care team and records:** load the selected profile's assigned associates and available records.
2. **APIs 9–14 — Reports:** use the selected record ID for documents, consolidated file, export, analysis, trends and report files.
3. **API 15 — Guidebook:** fetch the selected record's existing personalised-plan file.
4. **APIs 16–17 — Chat configuration and features:** obtain the profile session credentials and availability flags.
5. **APIs 18–20 — Chat:** call ASK-AI history, stream and feedback with API 16's session and token; request a fresh token through API 16 after a token-related 401.
6. **APIs 21–27 — Customer programs:** replace external care-team calls, then list therapy programs, summaries, program details, services and redemption history.
7. **APIs 28–31 — Notifications:** use the authenticated user's notification feed and device registration.
8. **Additional report list:** retrieve report summaries for the selected profile, optionally filtered by subscription.

### API requests

### API 7 — Assigned care team

List associates assigned to the selected profile.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/associates/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `center_id` | No | `<center_uuid>` | Repeatable: `?center_id=<uuid>&center_id=<uuid>`. An `X-Center-ID` header overrides query center IDs. |
| `role_id` | No | `<role_uuid>` | Require an active matching center role. |
| `search` | No | `Care` | Trimmed prefix search on associate account email or full name. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<associate_uuid>",
      "email": "care@example.com",
      "phone": "+91-9876543211",
      "first_name": "Care",
      "last_name": "Associate",
      "gender": "Female",
      "date_of_birth": null,
      "image": null,
      "is_active": true,
      "created_at": "<ISO-8601 timestamp>",
      "roles": [
        {
          "id": "<role_uuid>",
          "name": "Health coach",
          "role_tag": "Clinical",
          "is_system": false,
          "is_active": true,
          "created_at": "<ISO-8601 timestamp>",
          "updated_at": "<ISO-8601 timestamp>"
        }
      ],
      "role_ids": [
        "<role_uuid>"
      ],
      "created_by": {
        "id": "<user_uuid>",
        "email": null,
        "first_name": "Care",
        "last_name": "Associate",
        "image": null,
        "last_login": null
      },
      "contact_phone": "+91-9876543212",
      "title": null,
      "description": "Supports personalized health and lifestyle goals.",
      "tagline": "Health and lifestyle coach",
      "experience": 5.0,
      "qualifications": [],
      "professions": ["Health coach"],
      "has_verified_badge": false
    }
  ]
}
```

Roles are arrays and can be empty. Contact and demographic fields, image and `created_by` can be null. The displayed gender and role tag are labels. `is_active` currently defaults to true in this response; do not treat it as an independently verified account status.

`contact_phone` is the customer-facing associate contact number; `phone` remains the associate account phone and may differ. Title, description, tagline and experience can be null; qualifications and professions can be empty arrays. Title uses its display label and experience is expressed in years.

**Consumer change:** Pass the selected profile UUID and Biopeak JWT. This is an assigned team, not a global specialist directory; revise the reported global-directory fallback. Professional details are available through `title`, `description`, `tagline`, `experience`, `qualifications`, `professions` and `has_verified_badge`.

### API 8 — Profile records

Retrieve available Biopeak Health records for the selected profile.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/metsights-legacy/records/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

**Logic:** Biopeak Health selection is fixed. No query filters are accepted: `code`, `page`, `limit` and `search` are ignored. The response contains the default first page, up to 10 rows, without pagination metadata.

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
      "completed_at": "<ISO-8601 timestamp>",
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>",
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

`subscription` can be null. The complete record fields are shown above. `subscription_id` is not returned. Assessment information is nested under `subscription.assessment`; the record does not contain top-level `assessment_type`, `assessment_code`, `profile`, `demography` or `config`.

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights records not found."
}
```

**Consumer change:** Add profile UUID to the request and its cache identity. Retain `data[].id` as `record_id`. Do not rely on top-level assessment fields or old `count`/`next`/`previous`. An empty returned array is successful. The records list is under the selected profile's `metsights-legacy` namespace; record-specific calls use `/profiles/metsights-legacy/records/:record_id/`.

### API 9 — Record attachments

Retrieve document files for an owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/attachments/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `category_type` | No | `imaging_body_analysis` | Exact named category code; choices below. |
| `module_type` | No | `dxa_reports` | Exact named module code; choices below. |
| `file_type` | No | `dxa_core_scan` | Exact document-role code, not an extension; choices below. |

**Logic:** Invalid filter values are ignored. Old numeric category values such as `25`, `35` and `45` are not valid category codes. `page`, `limit` and `search` are ignored; up to 10 documents from the default first page are returned without pagination metadata.

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
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>",
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
        "created_at": "<ISO-8601 timestamp>",
        "updated_at": "<ISO-8601 timestamp>"
      }
    }
  ]
}
```

File-role/category/module/source values in the response are display labels; filters use codes. `name`, `file_type`, `redacted_file`, `attachment_date`, and optional metadata fields may be null. `questionnaire_date` and `assessment_date` represent the same assessment date.

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights record resource not found."
}
```

**Consumer change:** Use the legacy URL and record ID with Biopeak JWT. Keep rendering `data` as an attachment array; inspect `metadata` for categories. Replace numeric category selectors with named codes. The reported `limit: 1` call no longer restricts the result.

#### Attachment filter choices

**`category_type`:** `unknown`, `clinical_lab_diagnostics`, `functional_metabolic_tests`, `genetics`, `imaging_body_analysis`, `psychophysiology_performance`, `consultation_notes`, `risk_landscape_rootcause`.

**`module_type`:** `physical_measurement`, `diet_lifestyle`, `body_vitals`, `blood_diagnostics`, `advanced_blood_diagnostics`, `gut_intelligence`, `fitness`, `health_lifestyle`, `clinician_notes`, `precision_blood_diagnostics`, `urine_metabolites`, `saliva_panel`, `dxa_reports`, `gut_microbiome`, `genetics_insights`, `breathing_stress`, `fitness_strength`, `ultrasonography`, `evo_imaging`, `consent_forms`, `oligoscans`, `steroid_hormones`, `somfit_panel`, `risk_landscape`, `genetics_nutri_dna`, `genetics_health_insights`.

**`file_type`:** `dxa_core_scan`, `dxa_body_composition`, `dxa_segmental_analysis`, `breathing_stress_profile_report`, `breathing_stress_respiratory_report`, `breathing_stress_communication_style`, `breathing_stress_cognifit`, `usg_carotid_doppler`, `usg_neck`, `usg_abdomen_pelvis`, `usg_arterial_doppler`, `usg_venous_doppler`, `usg_sonomammogram`, `usg_scrotum`, `usg_follicular_tvs`, `usg_pelvic_tvs`, `usg_others`, `genetics_functional`, `genetics_nutri_dna`, `genetics_health_insights`, `genetics_breast_ovarian_cancer`, `genetics_comprehensive`, `genetics_pharmacogenomics`, `genetics_inherited_cancer`, `genetics_nutri_dna_pdf`, `genetics_nutri_dna_vcf`, `genetics_health_insights_pdf`, `genetics_health_insights_vcf`, `bugspeaks_report_pdf`, `bugspeaks_additional_report_xls`, `steroid_hormone_profile`, `steroid_hormone_nad_longevity`, `steroid_hormone_nutri_toxic`, `steroid_hormone_fatty_acid`, `steroid_hormone_neurotransmitter_profile`, `fitness_strength_pelvic_floor`, `fitness_strength_physical_assessment`, `fitness_strength_vo2_max`.

### API 10 — Consolidated report

Retrieve the consolidated report file for an owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/report/consolidated/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": {
    "file": "<download_url>"
  }
}
```

`file` can be null when the report object exists without a stored file. No query parameters are accepted.

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights record resource not found."
}
```

**Consumer change:** Replace the URL and authentication; retain `data.file` access. Handle a null file separately from a 404.

### API 11 — Email report export

Request report export for an owned record.

**Method:** `POST`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/export-reports/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `email` | Yes | `customer@example.com` | Valid recipient email; independent of the customer's saved email. |

```json
{
  "email": "customer@example.com"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Reports export request received."
}
```

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights reports export could not be requested."
}
```

**Consumer change:** Keep the email body and show the acknowledgement. Use Biopeak JWT and the selected record ID. The response confirms the request, not delivery; no `data` is required.

### API 12 — Report analysis

Retrieve analysis for an owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/report/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": {
    "id": "<record_id>",
    "age": 36,
    "data": {},
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

`data.data` is the saved analysis JSON and may be null, empty or populated. It is not a second response envelope. Its sections are variable and are passed through without merging or regeneration. The example uses an empty JSON object rather than inventing fixed analysis keys. `age` is serialized as a number.

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights record resource not found."
}
```

**Consumer change:** Replace the URL and authentication. Preserve the existing analysis renderer's access to `data.data`; the enclosing report retains `id`, `age`, `created_at` and `updated_at`. No query parameters are accepted.

### API 13 — Report trends

Retrieve historical parameter trends for an owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/report/trends/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": {
    "<section_name>": [
      {
        "code": "<category_code>",
        "category_name": "<category_name>",
        "parameters": [
          {
            "name": "<parameter_name>",
            "unit": "<unit>",
            "ref_lower": 0,
            "ref_upper": 100,
            "historical": [
              {
                "date": "2026-02-01",
                "value": 42
              }
            ]
          }
        ]
      }
    ]
  }
}
```

`<section_name>`, category codes/names and parameter names are data-dependent. Each category has `code`, `category_name` and `parameters`; each parameter has `name`, `unit`, `ref_lower`, `ref_upper` and `historical`. History entries contain date/value. Reference bounds and units can be null; values retain their stored representation. No available trend payload returns 404; consumers must also handle an empty object if it is returned. No query parameters are accepted.

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights record resource not found."
}
```

**Consumer change:** Use the legacy URL and Biopeak JWT; keep reading sections under `data`. Preserve the trends structure and individual histories.

### API 14 — Action-plan report files

Retrieve report files for an owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/report/files/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8; owned by the authenticated customer. |

**Logic:** No query parameters are accepted. The request returns page 1 with limit 50; caller `page`, `limit` and `search` are ignored. The response has no pagination metadata.

#### Response — `200 OK`

```json
{
  "detail": "MetSights record resource fetched.",
  "data": [
    {
      "id": "<report_file_uuid>",
      "name": "Lifestyle Blueprint",
      "file": "<download_url>",
      "file_type": "pdf",
      "category": "Lifestyle Blueprint",
      "metadata": {},
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>"
    }
  ]
}
```

`name` and `metadata` can be null. `metadata` is variable JSON. `file_type` is a stored string; `category` is a display label (`Unknown`, `Lifestyle Blueprint`, `Supplement Blueprint`, `Health Landscape`, or `Consolidated Report`).

#### Errors

`404 Not Found`

```json
{
  "detail": "MetSights record resource not found."
}
```

**Consumer change:** Replace the URL and authentication; preserve the file-array renderer. Do not promise all files when a record has more than 50, or display pagination controls for this route.

### API 15 — Guidebook

Retrieve the existing personalised plan for a customer-owned record.

**Method:** `GET`

**URL:** `<baseURL>/profiles/metsights-legacy/records/:record_id/personalised-plan/`

Requires a Biopeak customer JWT. The record must belong to one of the authenticated customer's mapped profiles; no profile ID is supplied in this URL.

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `record_id` | Yes | `<record_id>` | Record ID returned by API 8. |

No query parameters are supported; extra parameters are ignored.

#### Response — `200 OK`

```json
{
  "detail": "MetSights personalised plan fetched.",
  "data": {
    "id": "<record_id>",
    "file": "<personalised_plan_file_url>",
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

`id` is the corresponding record ID. Read the existing plan file URL from `data.file`; an empty stored file is returned as null. This request retrieves a plan and does not generate one.

#### Errors

`404 Not Found` — record unavailable, ownership mapping missing, or plan unavailable:

```json
{
  "detail": "MetSights personalised plan not found."
}
```

**Consumer change:** Replace the URL and authentication, retain the record ID and read the guidebook file from `data.file`. Handle 404 as an unavailable plan; do not substitute another report component.

### API 16 — Copilot chat configuration

Get the selected profile's fixed chat session and a fresh service-issued token.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/copilot-chat/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

**Authentication:** `Authorization: Bearer <Biopeak_access_token>`; the selected profile must belong to the authenticated customer. Query parameters are ignored.

**Logic:** Both profile and platform chat availability must be enabled. Biopeak registers the selected profile only when its saved session ID is missing; otherwise it requests a token for the saved session. The session ID stays fixed. Every successful configuration request returns a fresh ASK-AI token, which Django does not store. ASK-AI controls validity, currently 24 hours by default; existing tokens remain valid until their individual expiry or revocation. The response does not expose an expiry timestamp. Reuse the returned token for chat requests until expiry or revocation, then obtain another through this endpoint. Never use a different session ID with that token.

#### Response — `200 OK`

```json
{
  "detail": "Chat session initialized.",
  "data": {
    "id": "<copilot_session_uuid>",
    "session_id": "<session_id>",
    "token": "<copilot_token>"
  }
}
```

#### Errors

`403 Forbidden`

```json
{
  "detail": "Copilot chat is not enabled for this profile."
}
```

`503 Service Unavailable`

```json
{
  "detail": "ASK-AI token issuance is unavailable."
}
```

Other 503 details are `ASK-AI is not configured.`, `ASK-AI registration is unavailable.`, `ASK-AI is unavailable.`, `ASK-AI returned an invalid response.`, `ASK-AI returned incomplete credentials.`, `ASK-AI returned an invalid session ID.` and `ASK-AI returned a mismatched session ID.`. No local token is issued and an existing session ID is not replaced on these failures.

**Consumer change:** Use the selected Biopeak profile UUID. Read `data.session_id` and `data.token` from the single `data` envelope; do not read `data.expires_at` or assume a one-hour Django validity window. Send the token as `X-Api-Token` to APIs 18–20 on `https://ask-ai.biopeak.com/`. After a token-related 401, request configuration again and use the new token with the same session. The old response already had one `data` envelope; the frontend team's reported additional level was a consumer expectation, not a backend nesting change.

### API 17 — Profile features

Retrieve the selected profile's frontend availability flags.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/features/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "is_copilot_chat_enabled": true,
    "is_stable": false,
    "enabled_tabs": [
      "reports",
      "analysis",
      "action_plan",
      "care_team",
      "wellness"
    ],
    "updated_at": "<ISO-8601 timestamp>"
  }
}
```

Allowed tab codes: `reports`, `analysis`, `action_plan`, `care_team`, `personalised_plan`, `wellness`. The array can be empty. The `personalised_plan` tab can use API 15; a tab flag does not guarantee that a plan exists for the selected record.

**Consumer change:** Replace the host, profile ID and authentication. Use `enabled_tabs` and flags for visibility; obtain session credentials through API 16. The profile chat flag alone does not override platform chat availability.

### API 18 — Chat history

Retrieve history for the configured session.

**Method:** `GET`

**URL:** `https://ask-ai.biopeak.com/chat/history/:session_id/`

**Authentication:** `X-Api-Token: <token_from_API_16>`.

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `session_id` | Yes | <session_id> | Fixed session from API 16. |

No query parameters are defined. ASK-AI requires an active token issued for the requested session.

#### Response — `200 OK`

Returns the chat history JSON array directly, without a Biopeak `detail`/`data` envelope. An empty history is:

```json
[]
```

The complete history-item shape remains to be confirmed; no item fields are invented here. A missing header returns 422; an invalid, expired, revoked or mismatched token returns 401; an unreachable chat backend returns 503.

**Consumer change:** Replace the chat host and send `X-Api-Token`. Use the fixed session from API 16 and retain array response handling. On a token-related 401, obtain a new token through API 16. Do not move this call to `<baseURL>`.

### API 19 — Chat stream

Send a chat message and receive the streamed reply.

**Method:** `POST`

**URL:** `https://ask-ai.biopeak.com/chat/stream/:session_id/`

**Authentication:** `X-Api-Token: <token_from_API_16>`.

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `session_id` | Yes | <session_id> | Fixed session from API 16. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `message` | Yes | `Explain my latest report.` | Chat message string. |
| `media` | No | `[{"type": "image", "url": "<image_url>"}]` | Optional array; may be null. Each item requires a string `type` and accepts nullable `url` and `base64` strings. |

```json
{
  "message": "Explain my latest report."
}
```

#### Response — `200 OK`

Returns `text/event-stream` forwarded unchanged. There is no JSON `detail`/`data` envelope. The exact SSE event contents remain to be confirmed; preserve the existing SSE parser. A missing header or invalid payload returns 422; an invalid, expired, revoked or mismatched token returns 401.

**Consumer change:** Replace the chat host and send `X-Api-Token`. Keep the session ID in the path and omit it from the request body. Reuse the token for chat requests and renew through API 16 after a token-related 401. Do not read API 16's removed expiry field or move this call to `<baseURL>`.

### API 20 — Chat feedback

Submit feedback for an existing chat message.

**Method:** `POST`

**URL:** `https://ask-ai.biopeak.com/chat/feedback/:message_id/`

**Authentication:** `X-Api-Token: <token_from_API_16>`.

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `message_id` | Yes | <message_id> | Message identifier returned by the existing chat flow. |

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `rating` | Yes | `positive` | Accepts `positive` or `negative`. |
| `comment` | No | `Helpful explanation.` | Nullable string, maximum 2000 characters. |

```json
{
  "rating": "positive",
  "comment": "Helpful explanation."
}
```

#### Response — `200 OK`

Returns the chat feedback JSON directly; the complete success shape remains to be confirmed. No Biopeak response envelope is added. A missing header or invalid payload returns 422; an invalid, expired or revoked token returns 401; an unreachable chat backend returns 503. This route validates an active token and carries no session ID.

**Consumer change:** Replace the chat host and send `X-Api-Token`. Keep the message ID in the path, submit the documented rating/comment payload and preserve existing response handling. Renew through API 16 after a token-related 401. Do not move this call to `<baseURL>`.

### API 21 — Customer associates

Replace the external phone-identified care-team request with the selected profile's assigned team.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/associates/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `center_id` | No | `<center_uuid>` | Repeatable: `?center_id=<uuid>&center_id=<uuid>`. An `X-Center-ID` header overrides query center IDs. |
| `role_id` | No | `<role_uuid>` | Require an active matching center role. |
| `search` | No | `Care` | Trimmed prefix search on associate account email or full name. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<associate_uuid>",
      "email": "care@example.com",
      "phone": "+91-9876543211",
      "first_name": "Care",
      "last_name": "Associate",
      "gender": "Female",
      "date_of_birth": null,
      "image": null,
      "is_active": true,
      "created_at": "<ISO-8601 timestamp>",
      "roles": [
        {
          "id": "<role_uuid>",
          "name": "Health coach",
          "role_tag": "Clinical",
          "is_system": false,
          "is_active": true,
          "created_at": "<ISO-8601 timestamp>",
          "updated_at": "<ISO-8601 timestamp>"
        }
      ],
      "role_ids": [
        "<role_uuid>"
      ],
      "created_by": {
        "id": "<user_uuid>",
        "email": null,
        "first_name": "Care",
        "last_name": "Associate",
        "image": null,
        "last_login": null
      },
      "contact_phone": "+91-9876543212",
      "title": null,
      "description": "Supports personalized health and lifestyle goals.",
      "tagline": "Health and lifestyle coach",
      "experience": 5.0,
      "qualifications": [],
      "professions": ["Health coach"],
      "has_verified_badge": false
    }
  ]
}
```

**Consumer change:** Remove `phone` from query parameters and use Biopeak JWT/profile UUID. Keep reading `contact_phone` for the customer-facing associate number; `phone` remains available separately as the associate account phone. All previous professional fields are included alongside the additional current fields. `roles`/`role_ids` were already present in the checked old contract; a singular `role` consumer must use the array. Scope caches by profile and remove phone-based enabling. The old phone-scoped list could include assignments across the customer's profiles; this endpoint returns assignments for the selected profile.

### API 22 — Therapy programs

List therapy programs belonging to the selected profile.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/therapy-programs/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `active` | No | `1` | `0`/`1`; omitted or invalid values leave this filter unset. |
| `complete` | No | `1` | `0`/`1`; omitted or invalid values leave this filter unset. |
| `expired` | No | `0` | `1`: expiry before today; `0`: expiry today or later. Either excludes null expiry; omitted/invalid includes all. |

**Logic:** `active` applies to therapy-program activity. `complete` compares total sessions with used plus cancelled sessions. No phone query is used.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<program_uuid>",
      "uid": "BP-0001",
      "program_type": "therapy",
      "notes": null,
      "expires_at": "2027-01-01",
      "is_complimentary": false,
      "price": "1000.00",
      "services_count": 1,
      "sessions_count": 10,
      "sessions_cancelled": 1,
      "sessions_used": 2,
      "redeemable_centers": [
        {
          "id": "<center_uuid>",
          "code": "BLR",
          "name": "Biopeak Bengaluru",
          "image": null,
          "address": null,
          "address_line_1": null,
          "address_line_2": null,
          "city": "Bengaluru",
          "state": "Karnataka",
          "country": "India",
          "pincode": "560001",
          "staff_count": 1,
          "inactive_staff_count": 0,
          "customer_count": 1,
          "inactive_customer_count": 0,
          "is_active": true,
          "created_at": "<ISO-8601 timestamp>",
          "updated_at": "<ISO-8601 timestamp>"
        }
      ],
      "redeemable_centers_count": 1,
      "services": [
        {
          "id": "<program_service_uuid>",
          "service": {
            "id": "<catalogue_service_uuid>",
            "name": "Therapy session",
            "service_category": "Therapy",
            "service_category_code": "therapy",
            "image": null,
            "centers": [
              {
                "id": "<center_uuid>",
                "code": "BLR",
                "name": "Biopeak Bengaluru",
                "image": null,
                "address": null,
                "address_line_1": null,
                "address_line_2": null,
                "city": "Bengaluru",
                "state": "Karnataka",
                "country": "India",
                "pincode": "560001",
                "staff_count": 1,
                "inactive_staff_count": 0,
                "customer_count": 1,
                "inactive_customer_count": 0,
                "is_active": true,
                "created_at": "<ISO-8601 timestamp>",
                "updated_at": "<ISO-8601 timestamp>"
              }
            ]
          },
          "sessions_count": 10,
          "sessions_used": 2,
          "sessions_cancelled": 1,
          "redeem_code": "ABCD1234",
          "created_at": "<ISO-8601 timestamp>",
          "is_active": true,
          "can_redeem": true,
          "cancellation_reason": null,
          "cancelled_by": null,
          "cancelled_at": null,
          "program": {
            "id": "<program_uuid>",
            "uid": "BP-0001",
            "profile": {
              "id": "<profile_uuid>",
              "contact_email": "customer@example.com",
              "phone": "+91-9876543210",
              "first_name": "Example",
              "last_name": "Customer",
              "gender": "Male",
              "date_of_birth": "1990-01-01",
              "image": null,
              "is_main": true,
              "is_legacy": false,
              "is_onboarding_sent": false,
              "is_onboarding_completed": false,
              "is_converted": true,
              "created_at": "<ISO-8601 timestamp>",
              "updated_at": "<ISO-8601 timestamp>"
            },
            "program_type": "Therapy Program",
            "notes": null,
            "expires_at": "2027-01-01",
            "is_complimentary": false,
            "price": "1000.00",
            "services_count": 1,
            "sessions_count": 10,
            "sessions_used": 2,
            "redeemable_centers_count": 1,
            "cancellation_reason": null,
            "cancelled_by": null,
            "cancelled_at": null,
            "is_active": true,
            "created_at": "<ISO-8601 timestamp>",
            "updated_at": "<ISO-8601 timestamp>",
            "sessions_cancelled": 1,
            "created_date": "2026-01-01",
            "cancelled_date": null
          },
          "created_date": "2026-01-01",
          "cancelled_date": null
        }
      ],
      "created_date": "2026-01-01",
      "cancelled_date": null,
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>",
      "is_active": true,
      "created_by": {
        "id": "<user_uuid>",
        "email": null,
        "first_name": "Care",
        "last_name": "Associate",
        "image": null,
        "last_login": null
      }
    }
  ]
}
```

`notes`, `price`, `expires_at`, cancellation date and `created_by` can be null. Prices are decimal strings. `redeemable_centers` contains up to three centers; use the count separately. Nested `services` contains all fetched program-service rows, including parent `program`, service `created_date` and `cancelled_date`. Nested `program` uses the same representation as the overall program list below, including its profile context and display-label program type. Each nested `service.centers` contains up to three active catalogue-service centers with the full center shape shown above, or null when none exist; these previews are not restricted to program redeemable centers. `can_redeem` defaults to true here; API 25 provides the center-service availability calculation.

**Consumer change:** Use profile UUID/JWT and remove phone-dependent cache keys and enabling. `program_type` is now `"therapy"`; the old external list returned `"Therapy Program"`. Added fields include notes, complimentary status, price, redeemable centers, services and creator. Keep the returned program `id` for API 24.

### API 23 — Therapy summary

Retrieve therapy program/session totals for the selected profile.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/therapy-programs/summary/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

**Logic:** No query filters or pagination are accepted. Expired programs have expiry before today. Complete-program counts include active programs whose total sessions equal used plus cancelled. Expired sessions are total minus used sessions for expired programs.

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<profile_uuid>",
    "first_name": "Example",
    "last_name": "Customer",
    "programs_count": 1,
    "programs_expired": 0,
    "programs_inactive": 0,
    "programs_complete": 0,
    "sessions_count": 10,
    "sessions_used": 2,
    "sessions_cancelled": 1,
    "sessions_expired": 0,
    "centers_count": 1,
    "external_centers_count": 0
  }
}
```

**Consumer change:** Replace phone identity with profile UUID/JWT; remove phone-based enabling and query keys. Summary fields and therapy calculations remain the existing contract. An empty profile returns zero counters.

### API 24 — Therapy program detail

Retrieve an owned therapy program.

**Method:** `GET`

**URL:** `<baseURL>/programs/therapy-programs/:program_id/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `<program_uuid>` | Program `id` from API 22; must belong to the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<program_uuid>",
    "uid": "BP-0001",
    "profile": {
      "id": "<profile_uuid>",
      "contact_email": "customer@example.com",
      "phone": "+91-9876543210",
      "first_name": "Example",
      "last_name": "Customer",
      "gender": "Male",
      "date_of_birth": "1990-01-01",
      "image": null,
      "home_center": {
        "id": "<center_uuid>",
        "code": "BLR",
        "name": "Biopeak Bengaluru"
      },
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>"
    },
    "program_type": "therapy",
    "is_complimentary": false,
    "price": "1000.00",
    "notes": null,
    "expires_at": "2027-01-01",
    "sessions_count": 10,
    "sessions_used": 2,
    "sessions_cancelled": 1,
    "services_count": 1,
    "redeemable_centers": [
      {
        "id": "<center_uuid>",
        "code": "BLR",
        "name": "Biopeak Bengaluru"
      }
    ],
    "redeemable_centers_count": 1,
    "created_by": {
      "id": "<user_uuid>",
      "email": null,
      "first_name": "Care",
      "last_name": "Associate",
      "image": null,
      "last_login": null
    },
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>",
    "is_active": true,
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "created_date": "2026-01-01",
    "cancelled_date": null
  }
}
```

`profile` is the program's profile context, using `contact_email` for customer contact email. `home_center` can be null. Redeemable centers are limited to three. Creator/cancellation users can be null; a present user has the full shape shown by `created_by`. Expiry, notes, price and cancellation fields can be null.

**Consumer change:** Use the existing program detail route with JWT, without profile UUID or phone in the request. Retain this program object for program-status rendering and center context. Customers only read this route. Do not apply the top-level profile response's `email` naming to nested `profile.contact_email`.

### API 25 — Therapy program services

List services assigned to an owned therapy program.

**Method:** `GET`

**URL:** `<baseURL>/programs/therapy-programs/:program_id/services/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `program_id` | Yes | `<program_uuid>` | Program `id` from API 22; must belong to the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |

**Logic:** Optional `X-Center-ID: <center_uuid>` controls `can_redeem`: true means an active center-service assignment exists for that service at the requested center. Without the header, any active center assignment can qualify. A missing/unowned program produces an empty page when no owned rows match.

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<program_service_uuid>",
      "service": {
        "id": "<catalogue_service_uuid>",
        "name": "Therapy session",
        "service_category": "Therapy",
        "service_category_code": "therapy",
        "image": null,
        "centers": [
          {
            "id": "<center_uuid>",
            "code": "BLR",
            "name": "Biopeak Bengaluru",
            "image": null,
            "address": null,
            "address_line_1": null,
            "address_line_2": null,
            "city": "Bengaluru",
            "state": "Karnataka",
            "country": "India",
            "pincode": "560001",
            "staff_count": 1,
            "inactive_staff_count": 0,
            "customer_count": 1,
            "inactive_customer_count": 0,
            "is_active": true,
            "created_at": "<ISO-8601 timestamp>",
            "updated_at": "<ISO-8601 timestamp>"
          }
        ]
      },
      "sessions_count": 10,
      "sessions_used": 2,
      "sessions_cancelled": 1,
      "redeem_code": "ABCD1234",
      "created_at": "<ISO-8601 timestamp>",
      "is_active": true,
      "can_redeem": true,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "program": {
        "id": "<program_uuid>",
        "uid": "BP-0001",
        "profile": {
          "id": "<profile_uuid>",
          "contact_email": "customer@example.com",
          "phone": "+91-9876543210",
          "first_name": "Example",
          "last_name": "Customer",
          "gender": "Male",
          "date_of_birth": "1990-01-01",
          "image": null,
          "is_main": true,
          "is_legacy": false,
          "is_onboarding_sent": false,
          "is_onboarding_completed": false,
          "is_converted": true,
          "created_at": "<ISO-8601 timestamp>",
          "updated_at": "<ISO-8601 timestamp>"
        },
        "program_type": "Therapy Program",
        "notes": null,
        "expires_at": "2027-01-01",
        "is_complimentary": false,
        "price": "1000.00",
        "services_count": 1,
        "sessions_count": 10,
        "sessions_used": 2,
        "redeemable_centers_count": 1,
        "cancellation_reason": null,
        "cancelled_by": null,
        "cancelled_at": null,
        "is_active": true,
        "created_at": "<ISO-8601 timestamp>",
        "updated_at": "<ISO-8601 timestamp>",
        "sessions_cancelled": 1,
        "created_date": "2026-01-01",
        "cancelled_date": null
      },
      "created_date": "2026-01-01",
      "cancelled_date": null
    }
  ]
}
```

Service `image` and cancellation fields can be null. A present `cancelled_by` has `id`, `email`, `first_name`, `last_name`, `image`, and `last_login`, as shown by creator/user examples. `can_redeem` is service availability, not a complete authorization or remaining-session guarantee.

`program` contains the parent program and its profile context, using the overall program-list representation below. `created_date`, `cancelled_date` and `service.centers` are included alongside the existing fields. Service centers are active catalogue-service assignments within this program's redeemable centers, limited to three; no matches return null. Each center includes all fields shown in the example, preserving `id`, `code` and `name` and adding address, image, counts and activity details. `program.is_active` and the service row's `is_active` describe separate resources.

**Consumer change:** Use JWT and remove phone. Keep each row's `id` as the program-service identifier for APIs 26–27. Existing `service.centers`, `created_date` and `cancelled_date` consumers remain supported. Additional data includes nested `program`, category/image, cancelled sessions, `can_redeem` and cancellation reason/user.

### API 26 — Therapy service detail

Retrieve an owned therapy program-service.

**Method:** `GET`

**URL:** `<baseURL>/programs/program-services/therapy-services/:service_id/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `service_id` | Yes | `<program_service_uuid>` | API 25 item `id`, not nested `service.id`; must belong to the authenticated customer. |

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<program_service_uuid>",
    "service": {
      "id": "<catalogue_service_uuid>",
      "name": "Therapy session",
      "service_category": "Therapy",
      "service_category_code": "therapy",
      "image": null,
      "centers": [
        {
          "id": "<center_uuid>",
          "code": "BLR",
          "name": "Biopeak Bengaluru",
          "image": null,
          "address": null,
          "address_line_1": null,
          "address_line_2": null,
          "city": "Bengaluru",
          "state": "Karnataka",
          "country": "India",
          "pincode": "560001",
          "staff_count": 1,
          "inactive_staff_count": 0,
          "customer_count": 1,
          "inactive_customer_count": 0,
          "is_active": true,
          "created_at": "<ISO-8601 timestamp>",
          "updated_at": "<ISO-8601 timestamp>"
        }
      ]
    },
    "assignment_type": "Standalone",
    "assignment_type_code": "standalone",
    "sessions_count": 10,
    "sessions_used": 2,
    "sessions_cancelled": 1,
    "redeem_code": "ABCD1234",
    "created_date": "2026-01-01",
    "created_by": {
      "id": "<user_uuid>",
      "email": null,
      "first_name": "Care",
      "last_name": "Associate",
      "image": null,
      "last_login": null
    },
    "is_active": true,
    "created_at": "<ISO-8601 timestamp>",
    "updated_at": "<ISO-8601 timestamp>",
    "cancellation_reason": null,
    "cancelled_by": null,
    "cancelled_at": null,
    "cancelled_date": null,
    "program": {
      "id": "<program_uuid>",
      "uid": "BP-0001",
      "profile": {
        "id": "<profile_uuid>",
        "contact_email": "customer@example.com",
        "phone": "+91-9876543210",
        "first_name": "Example",
        "last_name": "Customer",
        "gender": "Male",
        "date_of_birth": "1990-01-01",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": true,
        "created_at": "<ISO-8601 timestamp>",
        "updated_at": "<ISO-8601 timestamp>"
      },
      "program_type": "Therapy Program",
      "notes": null,
      "expires_at": "2027-01-01",
      "is_complimentary": false,
      "price": "1000.00",
      "services_count": 1,
      "sessions_count": 10,
      "sessions_used": 2,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "is_active": true,
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>",
      "sessions_cancelled": 1,
      "created_date": "2026-01-01",
      "cancelled_date": null
    }
  }
}
```

Session counters and redeem code can be null if the therapy extension is unavailable. `assignment_type` is a label (`Standalone`/`Add On`); `assignment_type_code` is `standalone`/`add_on`. Creator/cancellation users and cancellation fields can be null.

`program` contains the parent program and its profile context, using the overall program-list representation below; it can describe a therapy or composite parent. `service.centers` contains up to three active catalogue-service centers within the parent program's redeemable centers, using the full center shape, or null when none match. Nested program cancellation users are UUIDs; the service's creator/cancellation users retain their nested user objects.

**Consumer change:** Use JWT and the program-service UUID. Keep reading nested `program` and `service.centers`. The frontend team's reported status rendering can read `program.is_active` directly; service `is_active` remains separate. Existing fields are retained alongside category/image, assignment type, cancelled sessions, creator and cancellation details.

### API 27 — Redemption history

List redemption history for an owned therapy program-service.

**Method:** `GET`

**URL:** `<baseURL>/services/therapy-services/:service_id/redemption-history/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `service_id` | Yes | `<program_service_uuid>` | API 25 item `id`, not nested `service.id`; must belong to the authenticated customer. |

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<redemption_uuid>",
      "redemption_type": "Redeem",
      "redeem_center": {
        "id": "<center_uuid>",
        "code": "BLR",
        "name": "Biopeak Bengaluru"
      },
      "redeemed_date": "2026-02-01",
      "redeemed_at": "<ISO-8601 timestamp>",
      "quantity": 1,
      "redeemed_by": {
        "id": "<user_uuid>",
        "email": null,
        "first_name": "Care",
        "last_name": "Associate",
        "image": null,
        "last_login": null
      }
    }
  ]
}
```

Rows are ordered by newest redemption date and time. Redemption labels are `Redeem` or `Cancel`. A present `redeemed_by` has the complete user shape shown; optional related values can be null where stored.

#### Errors

`404 Not Found`

```json
{
  "detail": "Therapy program service not found"
}
```

**Consumer change:** Use JWT and the program-service UUID; remove phone-dependent fetching. Render `quantity`, `redeem_center` and `redeemed_by` from each row. Keep local pagination.

### API 28 — Notifications

List notifications for the authenticated user.

**Method:** `GET`

**URL:** `<baseURL>/notifications/`

#### Query parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `read` | No | `0` | `0` unseen, `1` seen; omitted/invalid returns both. |

#### Response — `200 OK`

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<notification_uuid>",
      "title": "Report available",
      "body": "Your report is ready.",
      "notification_type": "Custom Event",
      "notification_type_code": "custom",
      "created_at": "<ISO-8601 timestamp>",
      "seen_at": null,
      "data": {}
    }
  ]
}
```

`body`, `seen_at` and notification `data` can be null. `data` is variable JSON. `notification_type` is the label and `notification_type_code` is the code: `custom`, `metsights.files.upload`, or `metsights.plan.upload`.

**Consumer change:** Use JWT; remove `phone` and phone-based enabling. Notifications belong to the authenticated user, not the selected family profile. For unread count request `read=0` and use `count`. Scope notification state by user, not profile.

### API 29 — Notification detail

Retrieve the authenticated user's notification and mark it seen.

**Method:** `GET`

**URL:** `<baseURL>/notifications/:notification_id/`

#### Path parameters

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `notification_id` | Yes | `<notification_uuid>` | Notification ID from API 28, owned by the authenticated user. |

**Logic:** The first detail read sets `seen_at`; subsequent reads retain it. Refresh the unread count after opening an unseen notification.

#### Response — `200 OK`

```json
{
  "detail": "Details.",
  "data": {
    "id": "<notification_uuid>",
    "title": "Report available",
    "body": "Your report is ready.",
    "notification_type": "Custom Event",
    "notification_type_code": "custom",
    "created_at": "<ISO-8601 timestamp>",
    "seen_at": "<ISO-8601 timestamp>",
    "data": {}
  }
}
```

#### Errors

`404 Not Found`

```json
{
  "detail": "Notification not found"
}
```

**Consumer change:** Use JWT and notification ID. Remove the phone query parameter; retain the notification fields from API 28.

### API 30 — Register device

Register the device's notification token for the authenticated user.

**Method:** `POST`

**URL:** `<baseURL>/notifications/register/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `token` | Yes | `<device_token>` | Nonblank notification token. |
| `project_id` | Yes | `health-app-36fd7` | Choices: `health-app-36fd7` (PWA), `biopeak-admin`. |

```json
{
  "token": "<device_token>",
  "project_id": "health-app-36fd7"
}
```

#### Response — `201 Created`

```json
{
  "detail": "Create success.",
  "data": {
    "token": "<device_token>",
    "project_id": "Biopeak App"
  }
}
```

**Consumer change:** Replace the external URL, add JWT and remove phone from the body. Registration must not wait for profile phone. An extra phone field is ignored and does not select the customer. The old registration response's `id` is not returned. Request `project_id` uses the code; the response uses its display label (`Biopeak App` or `Biopeak Admin`).

### API 31 — Deregister device

Remove matching device-token registrations for the authenticated user.

**Method:** `POST`

**URL:** `<baseURL>/notifications/deregister/`

#### Payload

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `token` | Yes | `<device_token>` | Token to remove for this authenticated user. |

```json
{
  "token": "<device_token>"
}
```

#### Response — `200 OK`

```json
{
  "detail": "Firebase token deregistered successfully"
}
```

**Consumer change:** Use JWT with `{token}`; remove phone from the body. Extra phone is ignored. Deregister before discarding the access token on logout, without a profile-phone guard. The response is an acknowledgement without `data`.

### Additional Phase 2 APIs

These provide report discovery and program dashboards in addition to the numbered migration calls.

| Method | Current URL | New URL | Usage |
| --- | --- | --- | --- |
| GET | `https://api.metsights.com/external/profiles/:profile_id/reports/` | `<baseURL>/profiles/:profile_id/metsights-legacy/reports/` | Profile report summaries |
| GET | New operation | `<baseURL>/profiles/:profile_id/programs/` | All program types |
| GET | New operation | `<baseURL>/profiles/:profile_id/programs/summary/` | Overall totals with per-type summaries |
| GET | New operation | `<baseURL>/profiles/:profile_id/programs/assessment-programs/summary/` | Assessment totals |
| GET | New operation | `<baseURL>/profiles/:profile_id/programs/consultation-programs/summary/` | Consultation totals |
| GET | New operation | `<baseURL>/profiles/:profile_id/programs/composite-programs/summary/` | Composite totals |

#### Profile report list

Retrieve available report summaries for the selected profile; no report ID is required.

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/metsights-legacy/reports/`

Requires a Biopeak customer JWT.

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected Biopeak UUID returned by API 5; must belong to the authenticated customer. |

**Query parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `subscription` | No | `<subscription_uuid>` | Exact report subscription UUID. Omit to retrieve reports without a subscription restriction. |

`page`, `limit`, `search` and other query parameters are ignored. Only the default first page of the report list is returned; this endpoint does not expose pagination counts or links and cannot be used to fetch later pages.

**Response — `200 OK`:**

```json
{
  "detail": "MetSights reports fetched.",
  "data": [
    {
      "id": "<record_id>",
      "subscription": {
        "id": "<subscription_uuid>",
        "assessment": {
          "id": "<assessment_uuid>",
          "name": "Biopeak Health",
          "assessment_type": "Biopeak Health",
          "assessment_type_code": "12",
          "description": null
        }
      },
      "age": 35.2,
      "file": "<report_file_url>",
      "is_shared": true,
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>"
    }
  ]
}
```

An empty list returns `200 OK` with `data: []`. `subscription` and `file` can be null; absent files remain null. Report `id` is the corresponding record ID and can be used with the existing legacy record/report-detail routes. The list includes available profile reports and is not restricted to precision reports. It returns summaries, without analysis, trends or component payloads.

**Errors:**

`404 Not Found` — missing report mapping or unavailable report-list data:

```json
{
  "detail": "MetSights reports not found."
}
```

`404 Not Found` — missing profile or profile owned by another customer:

```json
{
  "detail": "Customer profile with this ID not found."
}
```

**Consumer change:** Use the selected Biopeak profile UUID and JWT. Read the summary array directly from `data`; optionally supply `subscription`. Retain existing record/report-detail calls for analysis, trends and files. Do not interpret this first-page response as a complete report history.

#### All programs

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/`

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

**Query parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `page` | No | `1` | Page number; default 1. |
| `limit` | No | `10` | Page size; default 10, maximum 50. |
| `active` | No | `1` | `0`/`1`; omitted/invalid does not filter. |
| `expired` | No | `0` | `1`: expiry before today; `0`: today or later; either excludes null expiry. Omitted/invalid does not filter. |
| `program_type` | No | `therapy` | Codes: `therapy`, `assessment`, `consultation`, `composite`; omitted/invalid includes all. |

**Response — `200 OK`:**

```json
{
  "detail": "All data.",
  "count": 1,
  "next": null,
  "previous": null,
  "data": [
    {
      "id": "<program_uuid>",
      "uid": "BP-0001",
      "profile": {
        "id": "<profile_uuid>",
        "contact_email": "customer@example.com",
        "phone": "+91-9876543210",
        "first_name": "Example",
        "last_name": "Customer",
        "gender": "Male",
        "date_of_birth": "1990-01-01",
        "image": null,
        "is_main": true,
        "is_legacy": false,
        "is_onboarding_sent": false,
        "is_onboarding_completed": false,
        "is_converted": true,
        "created_at": "<ISO-8601 timestamp>",
        "updated_at": "<ISO-8601 timestamp>"
      },
      "program_type": "Therapy Program",
      "notes": null,
      "expires_at": "2027-01-01",
      "is_complimentary": false,
      "price": "1000.00",
      "services_count": 1,
      "sessions_count": 10,
      "sessions_used": 2,
      "redeemable_centers_count": 1,
      "cancellation_reason": null,
      "cancelled_by": null,
      "cancelled_at": null,
      "is_active": true,
      "created_at": "<ISO-8601 timestamp>",
      "updated_at": "<ISO-8601 timestamp>",
      "sessions_cancelled": 1,
      "created_date": "2026-01-01",
      "cancelled_date": null
    }
  ]
}
```

Rows are ordered newest first. `program_type` in this response is the display label: `Therapy Program`, `Assessment Program`, `Consultation`, or `Composite`; the filter takes codes. `sessions_count`, `sessions_used` and `sessions_cancelled` can be null when there is no therapy extension. `created_date` and `cancelled_date` are the parent program's dates; cancellation date can be null. This representation is also returned as nested `program` in service previews, service lists and therapy-service detail. Nested profile context uses `contact_email` and does not include the top-level selectable-profile `age` field. A non-null `cancelled_by` here is a user UUID, not a nested user object. Other nullable values follow their stored values.

#### Overall summary

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/summary/`

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

No query parameters are accepted.

**Response — `200 OK`:**

```json
{
  "detail": "Program summary retrieved.",
  "data": {
    "id": "<profile_uuid>",
    "first_name": "Example",
    "last_name": "Customer",
    "programs_count": 1,
    "programs_active": 1,
    "programs_inactive": 0,
    "programs_expired": 0,
    "services_count": 1,
    "services_active": 1,
    "services_inactive": 0,
    "results_count": 1,
    "documents_count": 1,
    "reports_count": 1,
    "raw_data_count": 0,
    "fetch_count": 1,
    "fetch_results_count": 1,
    "fetch_documents_count": 1,
    "fetch_pending_count": 0,
    "programs_by_type": {
      "therapy": 1,
      "assessment": 0,
      "consultation": 0,
      "composite": 0
    },
    "therapy": {
      "id": "<profile_uuid>",
      "first_name": "Example",
      "last_name": "Customer",
      "programs_count": 1,
      "programs_expired": 0,
      "programs_inactive": 0,
      "programs_complete": 0,
      "sessions_count": 10,
      "sessions_used": 2,
      "sessions_cancelled": 1,
      "sessions_expired": 0,
      "centers_count": 1,
      "external_centers_count": 0
    },
    "assessment": {
      "id": "<profile_uuid>",
      "first_name": "Example",
      "last_name": "Customer",
      "programs_count": 0,
      "programs_active": 0,
      "programs_inactive": 0,
      "programs_expired": 0,
      "services_count": 0,
      "services_active": 0,
      "services_inactive": 0,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "fetch_count": 0,
      "fetch_results_count": 0,
      "fetch_documents_count": 0,
      "fetch_pending_count": 0
    },
    "consultation": {
      "id": "<profile_uuid>",
      "first_name": "Example",
      "last_name": "Customer",
      "programs_count": 0,
      "programs_active": 0,
      "programs_inactive": 0,
      "programs_expired": 0,
      "services_count": 0,
      "services_active": 0,
      "services_inactive": 0,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "fetch_count": 0,
      "fetch_results_count": 0,
      "fetch_documents_count": 0,
      "fetch_pending_count": 0
    },
    "composite": {
      "id": "<profile_uuid>",
      "first_name": "Example",
      "last_name": "Customer",
      "programs_count": 0,
      "programs_active": 0,
      "programs_inactive": 0,
      "programs_expired": 0,
      "services_count": 0,
      "services_active": 0,
      "services_inactive": 0,
      "results_count": 0,
      "documents_count": 0,
      "reports_count": 0,
      "raw_data_count": 0,
      "fetch_count": 0,
      "fetch_results_count": 0,
      "fetch_documents_count": 0,
      "fetch_pending_count": 0
    }
  }
}
```

Overall program and service activity/expiry totals include all matching profile rows. Expired means expiry before today; inactive and expired counts can overlap. Result/document/report/raw-data/fetch totals are sums of stored service counters, including historical inactive rows. `programs_by_type` always has all four type codes. The nested `therapy` retains API 23's therapy metrics. Assessment, consultation and composite use program/service/result totals; they do not add therapy-session metrics. Empty summaries have zero counters.

#### Assessment summary

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/assessment-programs/summary/`

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

No query parameters are accepted. Only assessment programs and their services contribute to the counters; the fields have the same meaning as the overall totals.

**Response — `200 OK`:**

```json
{
  "detail": "Details.",
  "data": {
    "id": "<profile_uuid>",
    "first_name": "Example",
    "last_name": "Customer",
    "programs_count": 0,
    "programs_active": 0,
    "programs_inactive": 0,
    "programs_expired": 0,
    "services_count": 0,
    "services_active": 0,
    "services_inactive": 0,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "fetch_count": 0,
    "fetch_results_count": 0,
    "fetch_documents_count": 0,
    "fetch_pending_count": 0
  }
}
```

#### Consultation summary

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/consultation-programs/summary/`

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

No query parameters are accepted. Only consultation programs and their services contribute to the counters; the fields have the same meaning as the overall totals.

**Response — `200 OK`:**

```json
{
  "detail": "Details.",
  "data": {
    "id": "<profile_uuid>",
    "first_name": "Example",
    "last_name": "Customer",
    "programs_count": 0,
    "programs_active": 0,
    "programs_inactive": 0,
    "programs_expired": 0,
    "services_count": 0,
    "services_active": 0,
    "services_inactive": 0,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "fetch_count": 0,
    "fetch_results_count": 0,
    "fetch_documents_count": 0,
    "fetch_pending_count": 0
  }
}
```

#### Composite summary

**Method:** `GET`

**URL:** `<baseURL>/profiles/:profile_id/programs/composite-programs/summary/`

**Path parameters:**

| Name | Required | Example | Notes |
| --- | --- | --- | --- |
| `profile_id` | Yes | `<profile_uuid>` | Selected UUID returned by API 5; must belong to the authenticated customer. |

No query parameters are accepted. Only composite programs and their services contribute to the counters; the fields have the same meaning as the overall totals.

**Response — `200 OK`:**

```json
{
  "detail": "Details.",
  "data": {
    "id": "<profile_uuid>",
    "first_name": "Example",
    "last_name": "Customer",
    "programs_count": 0,
    "programs_active": 0,
    "programs_inactive": 0,
    "programs_expired": 0,
    "services_count": 0,
    "services_active": 0,
    "services_inactive": 0,
    "results_count": 0,
    "documents_count": 0,
    "reports_count": 0,
    "raw_data_count": 0,
    "fetch_count": 0,
    "fetch_results_count": 0,
    "fetch_documents_count": 0,
    "fetch_pending_count": 0
  }
}
```

### Questions

- What complete history-item JSON, SSE event examples and feedback success JSON should accompany ASK-AI APIs 18–20? Their request payloads and authentication are documented above; unconfirmed response contents are not invented.

## Phase: 3 — Deferred local reporting

After local coverage is verified and PWA consumers switch, replace the Phase 2 report routes with local profile data and retire the legacy/report compatibility and superseded external routes. Existing external routes remain available during Phase 2. There is no automatic local/remote fallback.

| API | Method | Current URL | New URL |
| --- | --- | --- | --- |
| 8 | GET | `<baseURL>/profiles/:profile_id/metsights-legacy/records/` | `<baseURL>/profiles/:profile_id/document-timelines/` |
| 9 | GET | `<baseURL>/profiles/metsights-legacy/records/:record_id/attachments/` | `<baseURL>/profiles/:profile_id/documents/` |
| 10 | GET | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/consolidated/` | `<baseURL>/profiles/:profile_id/documents/?document_type=metsights_pp&report_component=metsights-consolidated` |
| 11 | POST | `<baseURL>/profiles/metsights-legacy/records/:record_id/export-reports/` | `<baseURL>/profiles/:profile_id/programs/documents/export-email/` |
| 12 | GET | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/` | `<baseURL>/profiles/:profile_id/programs/results/` |
| 13 | GET | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/trends/` | `<baseURL>/profiles/:profile_id/programs/results/` |
| 14 | GET | `<baseURL>/profiles/metsights-legacy/records/:record_id/report/files/` | `<baseURL>/profiles/:profile_id/documents/?document_type=metsights_pp` |

Local timelines replace record-based date discovery with distinct descending collection months. Local document lists and export share filtering; invalid filters are ignored, and month only applies with a valid year. Component filters use valid provider-prefixed codes; historical null components are not inferred. No filename search is supported. Local active documents/results remain accessible when parent programs are inactive.

Analysis and trends remain separate per result; consumers select the desired result and read `analysis_data` and `trends_data`. Local export covers every matching document regardless of list pagination and acknowledges a nonempty ZIP export request. Copilot stays at `<baseURL>/profiles/:profile_id/copilot-chat/`. API 15 is available through the Phase 2 personalised-plan proxy; its Phase 3 local replacement is not yet defined. These are later consumer changes, not Phase 2 response substitutions.
