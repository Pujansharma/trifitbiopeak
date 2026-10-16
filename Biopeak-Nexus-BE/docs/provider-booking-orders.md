# Two-step provider booking orders

Paths are relative to `/programs/program-services/`. Existing admin/associate authentication applies. Booking creation and editing are local; only confirmation queues provider submission.

## Configuration

Provider administration and assessment provider selection expose the stored `booking_fields`, `booking_profile_fields`, `confirm_order_fields`, and `confirm_order_file_fields` arrays directly. These arrays are the source of truth for required inputs. The common confirmation serializer accepts optional `confirm_fields` JSON and optional `confirm_files`, a dictionary of named uploads. Configured scalar names are required keys inside `confirm_fields`; configured file names are required keys inside `confirm_files`. The selected provider's callback validates these inputs and its booking handler maps the upload internally. Remove obsolete `sample_collected_at` and `consent_file` names from BugSpeaks configuration. Strand validates its collection date; additional scalar keys retain their JSON values.

Booking and fetch profile fields retain the fixed choices `full_name`, `age`, `gender`, `date_of_birth`, `email`, and `phone`. No first-name/last-name profile choices were added. Configured dictionary keys must be present; extras are ignored, matching existing fetch validation. Provider-specific required values are checked before queueing.

| Provider callback | Booking fields | Required confirmation inputs | ProviderAPI.data credentials |
| --- | --- | --- | --- |
| `bugspeaks` | `kit_id` | None by default | `api_key` |
| `strand_life_sciences` | `kit_id` | `sample_collection_date`, `consent_file` | `client_id`, `client_secret`, `refresh_token`, `logged_user_email` |
| `metflux` | Empty for existing flow | None | `api_key`, `subscription_id` |

Strand also needs saved profile `full_name`, `gender`, `date_of_birth` and `Product.data.test_code/test_name`. Existing fetch credentials/configuration remain unchanged. EVO/5C stays fetch-only.

**Required configuration adjustment:** remove `sample_collection_date` and `consent_file` from Strand `booking_fields`. Configure Strand `confirm_order_fields: ["sample_collection_date"]` and `confirm_order_file_fields: ["consent_file"]` instead. BugSpeaks uses empty confirmation arrays by default; remove stored obsolete collection/consent names from its booking and confirmation arrays. The confirmation request sends `confirm_files.consent_file`; Strand maps that named document to its consent argument. Keep `kit_id` in booking configuration. Credentials stay exclusively in `ProviderAPI.data`; neither creation nor confirmation accepts credential inputs.

## Order creation and PATCH

`POST assessment-services/<program_service_id>/request-report/`:

```json
{
  "product_id": "<product UUID>",
  "data": {"kit_id": "KIT-1001"},
  "profile_data": {}
}
```

Supply configured patient fields in `profile_data`. Empty configuration permits omitted dictionaries, preserving MetSights product-only creation. Creation validates the active service/product/provider assignment and supported handler; provider API readiness is checked when confirming.

HTTP 201 creates an ORDER with `status_code: "pending"`, `is_submitted: false`, and zero attempts. It makes no provider call and schedules no task. Existing ORDER requests are rejected with HTTP 400, regardless of status or supplied values. The one-order-per-program-service database constraint remains unchanged.

For ORDER requests, `pending` plus `is_submitted=False` permits editing and initial confirmation. `pending` plus `is_submitted=True` means reports are awaited. Queueing disables editing; queued/running/submitted orders return the existing confirmation acknowledgement without another submission.

`PATCH result-requests/<request_id>/`:

The shared retrieve/update view also accepts PUT with the same editable fields and pending, unsubmitted order restriction.

```json
{"data": {"kit_id": "KIT-1002"}}
```

PATCH replaces either supplied `data` or `profile_data` snapshot and retains omitted snapshots. Supplied dictionaries must contain every configured key. Only pending, unsubmitted ORDER requests can be edited; product, remote identifiers, confirmation values and status are not writable. PATCH schedules nothing. A conditional update rejects stale edits if the snapshots changed or confirmation queued the order.

Detail/history reads expose `data.booking`, `profile_data`, the three most recent linked request-file records in `files`, lifecycle metadata, and linked results. `GET result-requests/<request_id>/files/` provides the complete paginated upload list using the same file-item serializer. GET and PATCH use one detail serializer; PATCH responses return the same full request shape with saved `data` and `profile_data`. Only those two dictionaries are writable.

## Confirmation and retry

`POST result-requests/<request_id>/confirm-order/` accepts `confirm_fields` and `confirm_files`. Strand uses multipart form data:

```text
confirm_fields: {"sample_collection_date":"2026-10-07"}
confirm_files.consent_file: <uploaded consent document>
```

BugSpeaks and MetSights with empty confirmation arrays accept JSON `{}`. For multipart requests, `confirm_fields` is a JSON-encoded form value alongside uploads named `confirm_files.<configured_name>`. Strand's collection date uses `YYYY-MM-DD`.

Confirmation validates saved configured snapshots, provider-specific booking values, confirmation fields, active configuration, and credentials before queueing. MetSights checks its existing birth-date/gender prerequisites when a remote profile is needed. Invalid requests schedule nothing.

Confirmation values are stored under `ResultRequest.data.confirmation`. Each configured upload is saved through a linked `ResultRequestFile` with its configured `field_name`, filename, and content type. Re-uploading on a failed, unsubmitted order replaces that named record's file. Strand's booking handler loads `consent_file` and passes its URL as consent. Request list/detail responses retain the existing file preview, and `GET result-requests/<request_id>/files/` retains its paginated response. A conditional ORM claim changes an unsubmitted pending/failed request to `queued`, freezes inputs, and schedules submission after commit. Saved-snapshot comparisons prevent a concurrent order edit from invalidating the inputs checked during confirmation.

Initial and repeated confirmation return HTTP 202 Accepted with only an acknowledgement message. No request object or processing progress is returned. Queued/running or successfully submitted requests are accepted without requiring new uploads or scheduling another submission. Background workers update progress; clients read it through request detail/history. Only one concurrent confirmation can claim the order. Failed unsubmitted requests can retry using the provider's effective confirmation inputs; saved booking/profile snapshots are reused. Cancelled orders cannot confirm. Successful remote orders use report retrieval rather than another submission.

## Provider submission and reports

Each integration owns its provider-specific validation and submission. Workers read credentials from `ProviderAPI.data` and booking values from saved `data.booking`.

Booking and order-request APIs remain generic and dispatch by provider callback and product callback. Provider-specific validation, submission, and report downloads live inside each integration; workers share coordination and persistence.

BugSpeaks sends JSON `{"data": {"data": {...}}}` to `BPK/api/client-kit-assignment/`. The inner object contains `Bugspeaks_ID` from saved `booking.kit_id`, `First_Name`, `Last_Name`, `Email_ID: "-"`, `Mobile_No` from saved profile phone, `Address: "-"`, `Pincode: "-"`, and default `Test_Type: "GMT"`. Saved `full_name` is split once into first and last names; missing name parts use `"-"`. Collection timestamps and consent uploads are absent from this provider request. Returned `Bugspeaks_ID` is saved immediately as `data.bugspeaks_id` with `is_submitted=True`; provider error payloads become readable failure details.

Both Strand booking handlers read collection date from `data.confirmation`, load the saved consent request-file record, and save returned `test_ref` as `data.trid`. The outbound request to Strand includes `age_type: "Years"`; missing result data is rejected and provider error messages are retained. The consent URL must be absolute and accessible to Strand. EVO/5C authentication and PDF-status calls match the supplied reference SDK; Biopeak's tuple returns and download streams are retained.

Separate handlers remain in `integrations/bugspeaks/utils/webhooks.py` and `integrations/strand_genomics/utils/webhooks.py`. Their task modules live at `webhooks/bugspeaks/tasks.py` and `webhooks/strand_genomics/tasks.py`. Internal webhook views receive payloads, start their respective provider task, and acknowledge HTTP 202. BugSpeaks stores the original payload, accepts `Bugspeaks_ID` plus stored lowercase identifiers, and dispatches supported `Project_Status` values through its handler dictionary. Normalized kit, dispatch, delivery, pickup, QC, and report-URL metadata is merged under `data.bugspeaks_lifecycle`, retaining previous metadata and unrelated request data. Submission merges its remote ID into the latest stored data; report workers save files in ServiceDocument and update processing status without replacing request data. Documents are located through their result/request relationships, with no duplicate document-ID map in request JSON.

Every BugSpeaks `Completed` callback explicitly fetches the PDF report and additional report, including callbacks received while another worker is running. A different hash creates a new ServiceDocument. The same hash updates the existing document's metadata and reuses its identical stored file. Failed downloads retain existing files. Strand checks order status and the expected test name, then explicitly retrieves PDF, VCF, and JSON through their separate APIs; previously saved output is retained and missing output can be filled. Workers update documents and processing status without overwriting lifecycle metadata. No callback timestamp columns or row locks are used in this flow. Database updates remain outside provider network calls, and affected counters are refreshed.

Manual `POST result-requests/<request_id>/refetch/` replaces report output using the saved provider identifier. It is independent of confirmation and never creates a remote booking. Unsubmitted orders cannot refetch; queued/running/cancelled orders retain their existing refetch restrictions. FETCH requests retain their default `queued` status.

Cancellation remains local. Queued and submitted orders retain their processing states. Thread recovery after process restart remains operator-managed. Pickup, questionnaire submission, and a durable queue are outside this change.

## Rollout and manual acceptance

The new ResultRequestFile model and Provider `confirm_order_fields` and `confirm_order_file_fields` arrays require user-generated migrations and explicit configuration. No existing configuration is automatically backfilled. New orders use `pending` with `is_submitted=False`. Pending orders with `is_submitted=True` await provider reports and cannot be edited. The model default remains `queued` for FETCH requests. Any persisted `draft` status must be converted to `pending` through the user-owned migration process. Migrations remain user-generated. Validation is limited to static review; no Python commands, tests, Bruno tasks, or memory updates are used. Apply the Strand provider configuration adjustment before new order creation. Historical unsubmitted orders retain their status and may need effective confirmation inputs on retry; successful orders continue using their saved remote IDs.

Manual acceptance scenarios:

1. Configure confirmation arrays and check the same arrays in provider selection. Send configured JSON values alongside two uploads named `confirm_files.consent_file` and `confirm_files.prescription_file`; verify each required file is checked and saved by name. Verify retry replaces each named file and that unconfigured values are ignored. Keep the paginated files response unchanged.
2. Create pending, unsubmitted orders for each provider; verify zero attempts and no outbound API call; reject duplicate creation.
3. PATCH configured snapshots; verify no task and rejection after queueing.
4. Reject missing Strand consent, invalid Strand dates, unusable saved inputs, and missing credentials without queueing.
5. Confirm BugSpeaks with `{}` under empty effective confirmation configuration; inspect nested JSON, `Bugspeaks_ID`, saved names/phone, placeholder address/pincode, and saved `bugspeaks_id`.
6. Confirm both Strand products; inspect confirmation collection date, consent URL, product test configuration, and saved `trid`.
7. Confirm MetSights with `{}` and verify its existing submission/report flow.
8. Race confirmations and pending-order edits; verify one queued submission with the validated snapshots.
9. Reconfirm queued/running/submitted requests; verify reuse. Retry failed unsubmitted requests; reject cancelled requests.
10. Exercise callbacks, partial reports, and manual refetch; verify no remote rebooking, retained lifecycle metadata, refreshed BugSpeaks completion reports, and retention of files after failed replacements.
