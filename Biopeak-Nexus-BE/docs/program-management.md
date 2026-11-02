# Program Management

## Overview

A **Program** is a composable container of services assigned to a customer. It represents a structured
engagement, such as a therapy plan, with a defined set of services the customer can redeem across
one or more centers.

Programs are issued at a single center (`center` FK) but can be redeemed at multiple centers
(`redeemable_centers` M2M). Each program has a type (for example, `therapy`), and the type-specific
model carries a `OneToOneField` back to `Program`.

---

## Architecture

```
services/
├── models.py                        # Service (global catalog, center-assigned via M2M)
└── programs/
    ├── models.py                    # Program, ProgramService, TherapyProgram
    └── utils/
        └── constants.py            # ProgramType
```

---

## Models

### Service

Global service catalog. A service can be assigned to multiple centers via the `centers` M2M.
Pricing is not stored here — it lives on `Program`.

| Field | Type | Purpose |
|---|---|---|
| `name` | CharField | Service display name |
| `centers` | M2M(Center) | Centers where this service is offered |
| `created_by` | FK(User, nullable) | Associate who created this service |

### Program

The core customer-facing container. One program per engagement.

| Field | Type | Purpose |
|---|---|---|
| `customer` | FK(Customer) | The customer this program belongs to |
| `center` | FK(Center) | Issuing center (where the program was created/sold) |
| `program_type` | CharField(ProgramType) | Discriminator for type-specific model |
| `notes` | TextField (nullable) | Internal notes |
| `expires_at` | DateField (nullable) | Program expiry date |
| `is_complimentary` | BooleanField | Whether this is a complimentary program (default: True) |
| `is_credit` | BooleanField | Whether this is a credit program (default: False); standalone therapy rejects both flags being true |
| `price` | DecimalField (nullable) | Program-level price |
| `credit_received` | DecimalField (nullable, 10 digits/2 decimal places) | Recorded credit amount; exposed for standalone therapy programs |
| `sessions_count` | PositiveIntegerField | Total sessions allotted in this program |
| `sessions_used` | PositiveIntegerField | Sessions consumed so far (default: 0) |
| `redeemable_centers` | M2M(Center) | Centers where this program can be redeemed |

### ProgramService

Links a program to a service. FK is to the global `Service`.
At booking time the scheduling engine resolves the correct center context from the
customer's chosen redemption center.

| Field | Type | Purpose |
|---|---|---|
| `program` | FK(Program) | Parent program |
| `service` | FK(Service) | Service included in this program |
| `created_by` | FK(User, nullable) | Associate who added this service to the program |

Constraint: `unique_together: (program, service)`

### TherapyProgram

Type-specific extension for therapy programs. One-to-one with `Program`
(enforced by `OneToOneField`). A program cannot have more than one type object.

| Field | Type | Purpose |
|---|---|---|
| `program` | OneToOneField(Program) | Parent program |

Add therapy-specific fields here as the domain grows.

---

## Constants

### ProgramType

Defined in `programs/utils/constants.py`.

| Constant | Value | Description |
|---|---|---|
| `THERAPY` | `therapy` | Therapy program |

Add new types here as the platform expands. Each new type requires a corresponding
type-specific model with a `OneToOneField` back to `Program`.

---

## Type Object Pattern

Each `program_type` value corresponds to exactly one type-specific model:

```
Program (program_type='therapy')
  └── TherapyProgram (OneToOne -> Program)
        └── therapy-specific fields

Program (program_type='consultation')        <- future
  └── ConsultationProgram (OneToOne → Program)
```

The `program_type` field is the discriminator — it tells you which related object to access
without querying all type tables. A program cannot have more than one type object.

---

## Frontend Flow

```
1. Associate selects redeemable centers for the program
   → filtered from the customer's associated centers

2. Services are shown based on selected centers
   → Service.objects.filter(centers__in=selected_centers).distinct()

3. Associate picks services for the program
   → ProgramService rows created (FK to global Service)

4. Program is saved with issuing center + redeemable centers + services
```

Validation that selected services are available at the chosen redeemable centers
is handled in the serializer `create` method, not at the model level.

---

## Booking Flow (Redemption)

When a customer books a session under a program service:

```
1. Customer picks a redemption center (from program.redeemable_centers)

2. Scheduling engine verifies the service is offered at that center:
   program_service.service.centers.filter(pk=chosen_center.pk).exists()

3. Availability is computed for that (service, center) combination

4. On booking: program.sessions_used is incremented
```

## Standalone Therapy Program Modifications

See [Therapy Program Modification ePRD](PRD-007-Therapy-Program-Modification.md) for the PATCH payload, response previews, and complete selected-center retrieval. See [Program Payments](PRD-010-Program-Payments.md) for receipts and credit/complimentary flag updates.

`TherapyProgramService.redeemable_centers` stores each assigned service's explicit center selections. These are separate from global catalog availability and must remain within the program's stored redeemable centers. Adding a program center never expands service selections automatically. The owning center has no redemption bypass. Center selections remain recorded if a service later becomes unavailable; redemption, booking, rescheduling, slots, and appointment completion revalidate availability. Program-level redeem-all validates all remaining active services before consuming any sessions.

`is_credit` and `is_complimentary` are writable during creation, program PATCH, payments POST, and assigned therapy-service PATCH. Flags are optional on PATCH and payments POST; omitted flags retain their stored values. The service PATCH accepts top-level flags and updates the shared standalone or composite parent Program, affecting all its services. Complimentary is `is_complimentary=true, is_credit=false`; credit is `false, true`; regular paid is `false, false`. There is no `is_paid` field. The `true, true` combination is rejected. When flags are supplied to the payments POST or service PATCH, credit and regular paid programs require an existing price. Set it through program PATCH first if needed. Zero assigned sessions provide no redemption allowance.

Standalone therapy creation accepts an initial `credit_received`; credit creation requires a non-null amount, allows zero, and rejects negative values. The field is read-only on program PATCH, and supplied amounts are removed from validated program data before validation or saving. No credit amount is required or validated during update, including for a null stored total. The payments POST adds each `amount_received` to the total using its existing receipt validation, treating a null total as zero and applying no cap tied to `price`. Turning credit off retains the amount. Amount-only receipt requests retain their previous behavior.

### Program Modification Audit

`ProgramAuditLog` records one row per changed Program field, with `program`, choice-valued `changed_field`, nullable text `previous_value`/`current_value`, nullable `created_by`, and inherited timestamps/UUID. It captures edits and cancellations through the therapy/composite API write paths, including Program cancellation metadata changed by service cancellation. History shares the mutation transaction; nested cancellation helpers do not produce duplicate entries.

The payments POST also audits each changed classification flag in the same transaction as the receipt and total increment. Assigned therapy-service PATCH audits changed parent flags in the same transaction as any session increments, without creating receipts or changing credit_received. Unchanged flags and the receipt total increment create no program audit entries. Failed operations commit neither receipts, flag changes, total changes, nor audit entries.

Initial creation, individual service/session edits, derived counters, automatic timestamps, and no-op field assignments are excluded. Monetary values use decimal strings, dates/timestamps use ISO strings, booleans use `true`/`false`, foreign keys use UUID strings, and program center sets use sorted JSON UUID arrays encoded as text. Null and blank text remain distinct. Existing edits are not backfilled. Direct database updates and maintenance commands do not produce audit rows automatically.

Staff can read paginated history at `GET /programs/<program_uuid>/history/`, including cancelled or expired programs. Customers cannot access it. See [Program Modification Audit API](program-modification-audit-frontend-eprd.md) for the contract.

### User-Owned Database Rollout

The `Program.is_credit` and `Program.credit_received` fields, `ProgramAuditLog` model, and `TherapyProgramService.redeemable_centers` relation require schema migrations. No migration files are generated or applied by Codex. New credit amounts remain null on existing rows; audit collection starts after deployment.

If the credit amount field already exists in the database under its previous name, the migration must rename it to `credit_received` and preserve stored amounts. Existing credit-amount audit rows also require their `changed_field` value to be updated to `credit_received` so historical API responses use the current field code.

Pause program writes and application traffic during rollout. Generate, review, and apply the schema migration yourself, then run the new one-time management command before serving the updated application:

```text
uv run manage.py backfill_therapy_service_redeemable_centers --created-before "<deployment-cutoff-ISO8601>"
```

Use the timestamp separating legacy rows from the new deployment. The command processes standalone therapy service lines created strictly before the cutoff and having no stored service center selections. It copies only their program's stored redeemable centers; it never adds a missing owning center or filters away currently unavailable selections. Lines without any stored program centers remain unredeemable until explicitly aligned through PATCH. Existing explicit service selections and composite programs are left untouched. Run this as deployment initialization while writes are paused, rather than as a recurring synchronization job.
