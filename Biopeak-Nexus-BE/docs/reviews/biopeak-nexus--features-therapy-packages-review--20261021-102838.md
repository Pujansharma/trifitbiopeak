# Composite assignments and program audit review

Review date: 2026-10-21, Asia/Kolkata. Repository: Biopeak-Nexus.
Branch: `features/therapy-packages-review`.
Base and reviewed HEAD: `af6c6b3072d0a26c20c18a308350eaa13c39467e` (`origin/main` merge base).
Scope includes the existing staged, unstaged, and relevant untracked consultation, composite, and therapy changes. Review complexity: 3/5.

## Walkthrough and findings

Consultation catalogue management, template membership, customer assignment, extensions, category counts, and repeated add-ons are already implemented. Two assignment routes have different legacy contracts. Therapy modifications also introduce credit flags and per-service center selections.

- **DJR-001 — Major, functional correctness, high confidence:** profile assignment lacks the center route's service-coverage validation, required expiry, and Packages write permission. Suggested adjustment: align both routes while retaining their payloads and profile-specific customer-link restriction. Suggested reviewer answer: preserve both routes and share assignment validation without weakening existing customer access restrictions.
- **DJR-002 — Major, data integrity, high confidence:** templates accept null therapy quantities, which assignment passes into non-null session allowances. Suggested adjustment/reviewer answer: retain null consultation quantities, require positive therapy quantities, and reject invalid existing templates with a field-specific validation error before assignment writes.
- **DJR-003 — Minor, maintainability, high confidence:** consultation-create and composite add-on views prepare write responses by reassigning serializer.instance. Suggested adjustment/reviewer answer: retain refreshed counts and previews while moving response preparation into serializers.

No external reviewer comments were supplied. All three findings require a focused adjustment or product decision; no sensitive external action was requested.

## Questions and decisions

1. Should the profile route enforce the center route's coverage, required expiry, and Packages write permission? Choices: Align both routes (recommended); Keep legacy behavior; Explain differences first. Selected: Explain differences first.
2. How should omitted/null therapy quantities be handled? Choices: Require quantity (recommended); Default to one session; Default to zero sessions. Selected: Require quantity.
3. Should response preparation move into serializers? Choices: Move into serializers (recommended); Keep current view reloads; Explain first. Selected: Move into serializers.
4. After explaining compatibility differences, which assignment rules should the profile route use? Choices: Align all rules (recommended); Align coverage only; Keep legacy behavior. Selected: Keep legacy behavior.
5. Audit scope/value format: Program fields only (recommended) versus Program and service fields; JSON fields (recommended) versus Text fields. Selected: Program fields only; Text fields.
6. Audit operations: Edits and cancellations (recommended); Edits only; Model only. Selected: Edits and cancellations. No creation audit or historical reconstruction.
7. History API: Defer API (recommended); Add staff history API. Selected: Add staff history API.
8. Credit scope: Model only (recommended); Therapy APIs too; All program APIs. Selected: Therapy APIs too.
9. Credit requiredness: Required for credit (recommended); Always optional. Selected: Required for credit, using merged PATCH state.
10. Credit disabled: Clear amount (recommended); Retain amount; Require explicit clearing. Selected: Retain amount.
11. Credit range: Zero through price (recommended); Nonnegative without a price cap; Signed amounts. Selected: Nonnegative without a price cap.

An interrupted earlier batch about audit scope, snapshots, and credit exposure returned no answers; it established no decisions and was superseded by the explicit choices above.

## Approved action ledger

1. DJR-002: positive therapy template quantities and assignment-time validation for existing templates.
2. DJR-003: serializer-owned consultation/create and add-on response preparation.
3. Add nullable Program.credit_price and therapy API support, required for resulting credit programs, retaining the amount when credit is disabled.
4. Add ProgramAuditLog, one row per changed Program field, nullable text before/after values, actor, and timestamp; atomically capture edits and cancellations and expose paginated staff history.
5. DJR-001: skip parity changes; retain the profile route's legacy permissions, expiry, and coverage rules.

Approved validation: static inspection and git diff --check only. No Python commands, tests, Bruno work, memory updates, migration generation/application, commits, pushes, or external review replies.
Model migrations belong to the user. Documentation and this record remain under docs/ according to project instructions.

## Implementation outcome

- **DJR-002 implemented:** `programs/composites/validators.py` validates positive therapy template quantities. Template creation and both center/profile assignment serializers invoke it before program writes. Consultation and assessment behavior is retained.
- **DJR-003 implemented:** consultation creation uses the serializer's refreshed center/count data without a view reload. Composite add-ons reload their response through the existing scoped queryset inside the serializer, preserving fresh previews.
- **DJR-001 intentionally retained:** the profile assignment route's coverage, optional expiry, and permission rules remain unchanged. Its only new assignment validation is the separately approved therapy quantity guard.
- **Credit implemented:** nullable `Program.credit_price`; therapy create/PATCH fields and therapy-only nested representations; merged-state requiredness, nonnegative input, retained amount when credit is disabled, and no price cap. Composite response shapes do not gain this field.
- **Audit implemented:** `ProgramAuditLog`, explicit field choices, text snapshots, and atomic recording through therapy/composite metadata and cancellation paths. Service cancellation helpers record parent Program changes and suppress nested duplicates when an outer program cancellation owns the audit.
- **History implemented:** `GET /programs/<uuid:pk>/history/`, staff-only permissions, owning/redeemable-center access, missing/inaccessible program 404, newest-first pagination, and no mutation endpoint. Inactive/expired programs remain readable when authorized.
- **Documentation:** PRD-005, PRD-007, customer therapy documentation, program management, and `docs/program-modification-audit-frontend-eprd.md` describe the new behavior and user-owned migration requirements.

Static re-review covered the URL/permission/serializer path, creation versus modification boundaries, credit transitions, null versus blank text, deterministic center serialization, unchanged edits, failed-operation rollback structure, inactive template lines, and cancellation call chains. No additional scoped actionable findings were identified.

`git diff --check` reported no whitespace errors. New untracked files were also inspected with `git diff --no-index --check` against `/dev/null`; no whitespace diagnostics were emitted (the no-index difference exit status is expected). Git emitted existing LF/CRLF normalization warnings.

No Python commands or runtime checks were executed. No tests were written or run. No migrations were generated/applied, Bruno files touched, memory updated, commits made, or external reviewer replies posted. Existing user-authored working-tree changes were preserved.

Required user action before deployment: generate/review/apply schema migrations for the new model and field alongside the branch's existing schema changes. Existing credit programs with null credit amounts need an amount on their next modification. History begins after deployment and does not reconstruct earlier edits. Direct database writes and maintenance commands are outside automatic audit collection.
