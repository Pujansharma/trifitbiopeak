# Assessment report requests in Biopeak Nexus

The assessment `request-report` endpoint selects a report-order handler using the selected product's provider callback and product callback. The request-handler registry is separate from the existing result-fetch registry used by `result-requests`.

Registered order providers include BugSpeaks gut microbiome and Strand NutriDNA/Genomic Health Insights. MetSights booking (`metflux` / `metsights_precision_mhap`) is temporarily disabled: new order requests and pending/failed unsubmitted order confirmations return validation errors without queueing submission. Existing submitted/queued/running confirmation acknowledgements retain their no-op behavior. Existing MetSights report fetching, webhooks, and manual refetch remain supported. See `provider-booking-orders.md` for configurable booking inputs and the additional providers. Unsupported callback combinations return a `product_id` validation error without creating a request.

The MetSights submission workflow below describes the retained integration helpers and existing order data; it is not currently available through booking creation or confirmation. API credentials for existing report retrieval are read from the selected product's provider API configuration.

To support another provider, register its booking handler under provider/product callbacks in `programs/program_services/utils/report_requests.py` and its confirmation validation function in `programs/program_services/utils/confirmation.py`. The common confirmation serializer accepts optional `confirm_fields` JSON and a `confirm_files` dictionary of named uploads. Order creation is local; confirmation validates and schedules submission after commit.

## Configuration

Assign an active MetSights Precision product (`metsights_precision_mhap`) to the assessment service. Its provider must use the `metflux` callback, have API access enabled, and have an active `ProviderAPI` containing:

```json
{
  "api_key": "<organization API key>",
  "subscription_id": "<MetSights BIOPEAK_HEALTH subscription UUID>"
}
```

The customer profile needs a birth date and a gender accepted by MetSights when a remote profile must be created. Existing `MetsightsProfile` mappings are reused. `METSIGHTS_BASE_URL` selects the API host; credentials for this flow come exclusively from `ProviderAPI.data`.

## Create pending order, then confirm or retry

Use the existing admin/associate authentication and program-service access conventions.

Order creation requires an active assessment, active assigned product, active provider, and supported callback handler. It creates no remote order. Confirmation additionally requires active API access and validates credentials from `ProviderAPI.data` before queueing.

```http
POST /programs/program-services/assessment-services/<program_service_id>/request-report/
Authorization: Bearer <access token>
Content-Type: application/json

{"product_id": "<assigned product UUID>"}
```

Creation returns HTTP 201 with `status_code: "pending"`, zero attempts, and `is_submitted=False`. Next call `POST /programs/program-services/result-requests/<request_id>/confirm-order/` with JSON `{}`. With empty configured confirmation arrays, MetSights has no additional inputs. Confirmation returns HTTP 202 Accepted with an acknowledgement only; background workers persist progress for detail/history reads. Pending, unsubmitted ORDER snapshots can be edited via PATCH before confirmation; see `provider-booking-orders.md`.

Report requests create a `ResultRequest` with `request_type=ORDER` and `is_submitted=False`. These read-only fields belong to the request, not to `ServiceResult`. Responses expose `request_type`, `request_type_code`, and `is_submitted`. Ordinary fetch requests have type `FETCH` and keep `is_submitted=False`. Their generated service results use `result_mode=FETCH`. Service results use `ResultType`; requests use `RequestResultType`, whose `FETCH` and `ORDER` values reference `ResultType`. Requests therefore exclude `UPLOAD` without duplicating the underlying values. Persistence copies `request_type` directly to `result_mode`. Results generated for an `ORDER` request use `result_mode=ORDER`, including webhook retrieval and manual refetch. Documents belong to these results and inherit the classification through their parent result; documents do not have a separate mode field.

One ORDER request is retained per program service; duplicate creation returns HTTP 400. Confirmation claims eligible pending/failed unsubmitted requests and schedules submission after commit. Queued/running or successfully submitted requests are reused without scheduling another submission. Failed unsubmitted requests may retry confirmation using saved booking/profile snapshots and existing remote progress. Cancelled orders cannot confirm; confirmation does not clear previous report output.

Successful submission sets `is_submitted=True`. The worker then tries report retrieval immediately; available report data creates the linked `ServiceResult` with `result_mode=ORDER` and its documents. If reports are not ready, subsequent webhooks trigger retrieval on the same request. Submission acknowledgements and remote IDs alone do not create empty result rows.

One request can own several service results, categorized by `document_type`, and each result can hold multiple documents. Shared `save_result_request_result` persistence uses `(result_request, document_type)` as its key and derives `result_mode` from the request type for all providers. For example, three type-A files and one type-B file belong to two results, with three and one documents respectively. MetSights report components remain grouped under one `METSIGHTS_PP` result. Providers returning multiple document types create separate results for those types, all carrying their parent request's mode.

MetSights booking is not registered with the confirmation submission dispatcher. Webhook retrieval and manual refetch retain `start_metsights_fetch_task` and `start_metsights_refetch_task`. Their worker checks fresh status and saves `running` before ordinary processing; no claim, lock, or timestamp arbitration is used. On completion or a handled processing failure, it persists `data`, `is_submitted`, status and failure details, then refreshes report/document counts. Callback receipt timestamps and local cancellation remain preserved. Simultaneous processing remains an accepted risk under the single-user workflow.

Report retrieval runs separate analysis, report-document, paginated-file and trends functions. Report-document API calls use a dispatch map; file categories use an extension mapping. The coordinator collects component errors without comparing error messages or checking component names. Missing components, including empty downloaded files, leave requests `PENDING` when no report output was saved, or `PARTIALLY_FETCHED` when output exists. Placeholder record metadata alone does not count as available output. Configuration failures and exceptions remain worker failures. Successful output is retained for subsequent callbacks; explicit refetch still resets it first.

The caller creates a remote record only when `ProgramService.data.record_id` is absent and saves the returned ID immediately. It queries active source results and active documents within the same program, excluding generated MetSights results. A single flattened DataFrame contains result metadata, `data`, and document fields. A left join retains JSON-only results. The caller groups by source result, creates one attachment, then uploads its files in a nested loop. JSON is sent unchanged when the attachment is created; it is assumed immutable and is not versioned.

Blood, OligoScan, urine, cortisol, EVO and SOMFIT omit `file_type`. DXA, USG, breathing/stress, genetics, hormones and fitness use the PRD mappings. Pelvic floor and VO₂ max use `fitness_strength`. NutriDNA and Health Insights associate JSON and PDF/VCF files with their dedicated module session. Bugspeaks distinguishes PDF from spreadsheets. Uploads send `has_pii=false`; ambiguous or unsupported inputs are recorded as submission errors.

## Inspect progress

```http
GET /programs/program-services/assessment-services/<program_service_id>/result-requests/
GET /programs/program-services/assessment-services/<program_service_id>/result-requests/?mode=order
GET /programs/program-services/assessment-services/<program_service_id>/result-requests/?mode=fetch
GET /programs/program-services/result-requests/<request_id>/
```

The list accepts `mode=fetch` or `mode=order` to filter by `ResultRequest.request_type`. Omitting `mode` returns all request types; unknown values are ignored. The filter can be combined with `status` and pagination.

For ORDER requests, `pending` with `is_submitted=False` means a local, editable order awaiting confirmation; `pending` with `is_submitted=True` means reports are awaited. `queued` means waiting for a worker; `running` means processing; `submitted` means all eligible inputs were uploaded. Any non-OK HTTP response during report retrieval or report-file download is treated as `METSIGHTS_REPORT_UNAVAILABLE`; no status code has special handling. Only successful responses are parsed as report JSON. `partially_fetched` means some artifacts were saved, `completed` means all expected components were retrieved, and `failed` records a processing failure. `cancelled` prevents a task from starting. Mid-operation cancellation is outside this flow.

`ResultRequest.data.submission` stores session IDs, uploaded document IDs, errors and the submission timestamp. `data.artifacts` maps report roles or remote file IDs to local documents. `data.fetch_errors` lists components still unavailable or failed.

## Webhook retrieval

Send the existing webhook envelope to `/webhooks/metsights/`:

```json
{"scope": "reports.available", "data": {"record_id": "<record ID>", "status": "available"}}
```

```json
{"scope": "reports.export", "data": {"record_id": "<record ID>", "files": []}}
```

```json
{"scope": "files.upload", "data": {"record": {"id": "<record ID>"}, "attachment": {}}}
```

The receiver resolves the saved record ID and requests a fetch with `replace_existing=False`. Unknown records are acknowledged without creating results. Existing export emails and upload notifications remain in place. The ingestion path retrieves URLs from authenticated MetSights APIs; it does not download URLs supplied by the webhook.

Fetch order is analysis, the three dedicated PDFs, consolidated report, paginated additional files, then trends. Successful components are saved immediately. Missing components do not stop later artifacts. Existing JSON components and documents are preserved, report roles and remote IDs are tracked, and identical file content is deduplicated within the result. Result and document counters are refreshed.

A supported webhook starts its retrieval task using the saved record ID. Existing output remains intact, and repeated callbacks fill missing components.

The explicit `/result-requests/<request_id>/refetch/` action deletes the request's existing results and documents, clears fetched-artifact bookkeeping, and requeues the same request for a fresh result set. It does not resubmit source inputs or reset `is_submitted`; it retrieves reports for the existing order. Previous output is not restored if retrieval fails. Webhooks do not reset results: repeated callbacks continue filling missing components. Running, queued and cancelled order requests cannot be manually refetched.

## Failure recovery and rollout

Known successful remote IDs survive failures and are reused on retry. Submission eligibility is checked through ResultRequest status; no intermediate operation marker is stored or checked in its data.

Threads have no automatic recovery after a process restart. For a stranded queued/running request, first confirm its worker has stopped, then reset its status to failed through an operator-controlled database update before requesting submission again. Fetch-only recovery can be triggered by a repeated webhook after resetting the stranded status; manual refetch deliberately clears previous results before retrieving a fresh set.

The user generates and applies migrations. This change adds `ResultRequest.request_type` (default `FETCH`) and `is_submitted` (default `False`), and replaces the provider-specific conditional uniqueness constraint with one ORDER request per program service. Existing requests with `data.metsights_submission=true` must be backfilled to `ORDER` before switching application code to the new fields; use the saved submission progress to backfill successfully submitted orders. Existing ordinary fetch requests remain `FETCH` with `is_submitted=False`. The application no longer uses the provider-specific JSON marker. No migration files were generated or run by the agent.

## Large file transfers

Only file download and upload requests use `timeout=60` and streaming. Downloads return `((file, content_type), None)` on success or `((None, None), error)` on failure. The inner tuple always exists. The live HTTP stream is saved directly to final storage. The caller closes the stream after persistence. Empty-file checks happen after storage persistence; SDK and submission helpers let request exceptions propagate to the worker. The saved file is read once more to calculate its hash; duplicate content reuses the existing document and removes the redundant stored copy. There is no temporary download file. Uploads use the standard Requests `files=` multipart interface, as selected by the user; this buffers the multipart request body in memory. `stream=True` on the upload applies to the response, not the request body. No multipart streaming package is used. Staging and production S3 source reads spill to disk after 1 MiB. Ordinary JSON requests have no explicit timeout. S3 source reads still require sufficient disk space for storage-backend spooling; a 60-second timeout applies to network inactivity rather than total transfer duration.
