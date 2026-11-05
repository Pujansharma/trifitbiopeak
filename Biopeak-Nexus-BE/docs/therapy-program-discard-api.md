# Therapy Program Discard API

Discard is permanent and independent of cancellation. Both therapy programs and
their assigned therapy services expose the read-only boolean `is_discarded`,
which defaults to `false`. Clients discard records through the actions below;
detail PATCH requests cannot change this flag.

Both models also expose read-only `discarded_by` as a nested user object or
`null`. Discard actions record the authenticated request user. Program discard
uses that user for each newly discarded child service; existing discarded
children retain their original attribution. Repeated discard never overwrites
the original user. Historical discards without attribution and records whose
discarding user has been deleted return `null`.

The assigned-service lists at
`/programs/therapy-programs/<program_id>/services/` and
`/profiles/<profile_id>/programs/therapy-programs/<program_id>/services/` accept
`discarded=0|1`: `0` returns non-discarded assignments and `1` returns discarded
assignments. Omit the parameter to return both. Other values are ignored.
The filter applies before pagination and does not change parent totals.

## Actions

| Resource | Method | URL |
|---|---|---|
| Therapy program | POST | `/programs/therapy-programs/<program_id>/discard/` |
| Assigned therapy service | POST | `/programs/program-services/therapy-services/<program_service_id>/discard/` |

Both actions require staff JWT authentication (admin or associate) and a valid
`X-Center-ID` header. Associates must have an active assignment at that center;
admins do not require a center assignment. The IDs
are assigned program/service UUIDs, not catalogue service IDs. Composite-owned
therapy services are outside this API and return not found.

Each discard lookup is filtered by the owning program's center using
`X-Center-ID`. Programs and service assignments owned by another center return
the corresponding not-found response.

Send an empty JSON body:

```json
{}
```

Success uses the existing POST action status, `201 Created`, and envelope:

```json
{
  "detail": "Create success.",
  "data": {
    "is_discarded": true,
    "discarded_by": {
      "id": "019b6927-81eb-74c2-bed5-82604bc4d110",
      "email": "staff@example.com",
      "first_name": "Aarav",
      "last_name": "Shah",
      "image": null,
      "last_login": null
    }
  }
}
```

Already-discarded records return the same successful response without repeating
the operation. Cancelled, expired, partially-used, and fully-used records can
also be discarded. There is no restore action.

## Effects and totals

- Discarding a program also discards all its assigned therapy services,
  including previously cancelled services.
- Discarding a single service does not discard or cancel its parent program,
  even when it is the last non-discarded service.
- Discard preserves all active flags, cancellation metadata, individual service
  session counters, redemption history, and existing linked appointments.
- Parent `sessions_count`, `sessions_used`, `sessions_cancelled`,
  `services_count`, and `services_cancelled` exclude discarded lines.
  Non-discarded cancelled lines remain included. Discarding a whole program
  makes all five totals zero; redeemable-center counts are unchanged.
- Discarded programs and services remain readable with `is_discarded: true`.
  They cannot be booked, offered as available slots, redeemed, extended, or
  cancelled. Existing linked appointments remain unchanged at discard time;
  subsequent linked completion or rescheduling cannot use the discarded line.
- Service additions cannot reuse discarded assignments, and discarded programs
  cannot receive additions or normal detail updates.

For example, three one-session services with one cancelled have
`sessions_count: 3` and `sessions_cancelled: 1`. Discarding the cancelled line
changes those totals to `2` and `0`, preserving that line's own session counts
and cancellation history. The session-recomputation command follows the same
exclusion rules and does not reset discarded lines' session counters.

## Schema deployment

The `is_discarded` flags and `discarded_by` user relationships require schema
migrations generated and reviewed by the project owner before deployment.
The user relationships are nullable; historical discard attribution is not
backfilled. The new attribution fields do not change existing totals.
