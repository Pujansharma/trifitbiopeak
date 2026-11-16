# WhatsApp Background Jobs Implementation Plan

> **Historical plan (2026-11-11).** WA shipped. Google later mirrored this pattern (2026-11-15) via `GoogleCalendarOutbox`; shared `CommunicationOutbox` removed. Keep for archive; do not execute as-is.

**Goal:** Dedicated WhatsApp outbox table, SQS batch workers, and EventBridge reminder cron; detach WA from shared communication outbox.

**Architecture (as shipped later):** `WhatsAppOutbox` + `integrations/communications/whatsapp/{outbox,dispatch}.py`; Google on `GoogleCalendarOutbox` + `integrations/google_calendar/{outbox,dispatch}.py`; CDK from `infra/integrations.yaml`.

**Tech Stack:** Django 6, boto3 SQS, AWS CDK (Python), EventBridge Scheduler, ECS Fargate

**Spec:** `docs/superpowers/specs/2026-11-11-whatsapp-background-jobs-design.md`

## Global Constraints

- No agent-created Django migration files
- No `select_for_update()`
- No CloudWatch alarms; keep existing image tagging
- CODING_RULES + MEMORY

## Review Focus

- Double SQS delivery must not double-send Meta (claim idempotency)
- Pre-care must not send before confirmed ACCEPTED
- Google uses its own outbox/SQS path (not a shared wake)
- Empty job-id lists must never publish
- Webhook writes `WhatsAppOutbox` only (never a shared communication outbox)

---

### Task 1: Model + constants + admin

**Files:** `integrations/utils/constants.py`, `integrations/models.py`, `integrations/admin.py`

- [ ] Add `WhatsAppOutboxStatus` (same values as communication outbox statuses)
- [ ] Add `WhatsAppOutbox` (appointment FK, template fields, status, wamid, attempts, timestamps)
- [ ] Register admin
- [ ] Document: user owns migration

### Task 2: WhatsApp outbox + dispatch modules

**Files:** Create `integrations/communications/whatsapp/outbox.py`, `dispatch.py`

- [ ] Enqueue / claim / process / pre-care / webhook apply on `WhatsAppOutbox`
- [ ] `dispatch_whatsapp_job_ids` chunks ≤10, JSON body, never empty
- [ ] Optional receipt-handle delete after process

### Task 3: Detach shared outbox

**Files:** `integrations/communications/outbox.py`, `service.py`, webhook view, sweep

- [ ] `enqueue_appointment_message` → Google only + Google wake; WA via new module
- [ ] Remove WA from `CHANNEL_PROCESSORS` / pending queryset
- [ ] Remove Meet-defer WA wakes from Google finish
- [ ] Reminders query `WhatsAppOutbox`; remove reminder from sweep

### Task 4: Commands + settings

**Files:** management commands, `core/settings/*`

- [ ] `process_whatsapp_outbox`, `run_whatsapp_reminder_schedule`
- [ ] `WHATSAPP_OUTBOX_QUEUE_URL`

### Task 5: Infra YAML + CDK

**Files:** `infra/integrations.yaml`, constructs, stack, app entry

- [ ] WA queue + DLQ; scheduled reminders cron Asia/Kolkata
- [ ] Reuse cluster/VPC via props/lookups; no alarms

### Task 6: Tests + docs

**Files:** `integrations/tests/test_whatsapp_outbox.py`, MEMORY, ENVIRONMENT

- [ ] Point WA tests at `WhatsAppOutbox`
- [ ] Google tests still pass
