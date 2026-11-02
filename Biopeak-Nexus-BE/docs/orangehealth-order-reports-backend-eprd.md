# Backend ePRD: OrangeHealth Order Reports

Automatically attach OrangeHealth webhook reports to the person's selected program service, using the existing
ServiceResult and ServiceDocument conventions.

## What to do, when

| When                                                                | Backend behavior                                                                                                                                                                                                                                        |
|---------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Creating an OrangeHealth diagnostic order**                       | Require `program_service_id` for each person. Derive the program and customer profile from that service. Validate an active OrangeHealth Blood product assignment and resolve the product without another user input. `program_id` is only a UI filter. |
| **The diagnostic order is successfully created**                    | Store the person-to-program-service link and create a local ResultRequest with `request_type="order"`. Store the existing order identifiers and relevant data. **Creating this ResultRequest must not create or submit another OrangeHealth order.**    |
| **A webhook arrives**                                               | Verify its signature, persist the original payload, and update diagnostic-order metadata/status as currently supported. Resolve the order and the specific person using the provider payload. Backend engineers own the payload mapping.                |
| **`test.completed_sent` or `order.completed` arrives with reports** | After saving the event, start background report processing using the existing project pattern. Download only reports belonging to that order/person.                                                                                                    |
| **Reports are processed**                                           | Create or update one Blood ServiceResult under that person's linked ORDER ResultRequest. Store relevant raw provider JSON and attach downloaded PDFs as ServiceDocuments, including filename, content type, and file hash.                              |
| **More reports arrive for the same order/person**                   | Add them to the same ServiceResult. Retain previously saved PDFs and metadata. Repeated callbacks must not create duplicate results or identical documents.                                                                                             |
| **Results or documents change**                                     | Refresh existing result, program-service, request, and composite-program counters. Updating the service means updating its results and counters; it does not redeem an entitlement.                                                                     |
| **Report processing fails or is incomplete**                        | Retain the webhook data and successfully saved PDFs. Record pending, partial, completed, or failed processing on the ResultRequest as appropriate. Recovery retries report processing only and must never submit another provider order.                |
| **A legacy order has no program-service link**                      | Continue storing webhook metadata on the diagnostic order. Do not infer a destination or automatically attach documents.                                                                                                                                |

## Dates and data

- Follow the existing OrangeHealth fetch convention: order creation date becomes `sample_collection_date`; order
  completion date becomes `report_generation_date`.
- Preserve previously known dates when later callbacks omit them; unavailable dates remain null.
- Store raw provider data as JSON metadata. No separate downloadable JSON document or clinical-value extraction is
  required.
- Confirmation or other generic ResultRequest actions must never submit these locally recorded diagnostic orders.

## Acceptance

For each person in a newly linked order, webhook PDFs appear under the selected program service with raw metadata,
dates, and correct counters. Incremental reports and repeated callbacks preserve existing output without duplication,
and ResultRequest processing makes no additional OrangeHealth booking.
