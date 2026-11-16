# WhatsApp Dedicated Background Jobs — Design

**Date:** 2026-11-11  
**Status:** Shipped (WA). Google later followed the same pattern (2026-11-15): `GoogleCalendarOutbox` + SQS; shared `CommunicationOutbox` removed.

## Intent

Take WhatsApp off the shared outbox + wake + sweep path. Give WA its own table, SQS job queue, on-demand Fargate workers, and a clock-aligned reminder schedule so future integrations can copy the same pattern.

## Goals

- WA never uses a shared wake queue or `sweep_jobs.sh`.
- Database remains source of truth; SQS carries batches of job ids (≤10).
- Scale workers as `ceil(N/10)` via one SQS message per non-empty batch.
- Confirmed (and other first-wave events) process before pre-care; pre-care only after confirmed `ACCEPTED` (Meta API accept + wamid).
- Webhooks update the new table by `wamid`.
- Config-driven infra via `infra/integrations.yaml` + CDK.

## Non-goals (v1)

- No Meet/Google deferral for WA.
- No CloudWatch alarms/dashboards.
- No Git SHA tagging change (keep existing deploy image tags).
- Agent does not create Django migration files (user owns migrations).

## Naming

| Concept | Name |
|--------|------|
| Model | `WhatsAppOutbox` |
| Status choices | `WhatsAppOutboxStatus` |
| Events | reuse `CommunicationEventType` |
| Queue setting | `WHATSAPP_OUTBOX_QUEUE_URL` |
| YAML integration | `whatsapp` |
| Queue name | `whatsapp-outbox-jobs` |
| Process command | `process_whatsapp_outbox` |
| Reminder schedule command | `run_whatsapp_reminder_schedule` |
| Scheduled YAML key | `whatsapp_reminders` |
| Cron | `cron(0/15 * * * ? *)` timezone `Asia/Kolkata` |

## Flow

```text
Book/cancel/... → WhatsAppOutbox PENDING → dispatch chunks of ≤10 ids → SQS
  → Fargate process_whatsapp_outbox --job-ids ... [--receipt-handle ...]
  → claim → send → ACCEPTED → maybe enqueue pre-care → DeleteMessage

Webhook → WhatsAppOutbox by wamid

EventBridge :00/:15/:30/:45 Asia/Kolkata
  → run_whatsapp_reminder_schedule (enqueue due + dispatch)
```

**Superseded (2026-11-15):** Google now uses `GoogleCalendarOutbox` + `GOOGLE_CALENDAR_OUTBOX_QUEUE_URL` + `run_google_calendar_schedule` (same pattern). Shared `CommunicationOutbox` is gone.

## Reliability

- Claim = conditional `UPDATE` (no `select_for_update`).
- Worker deletes SQS message after orderly exit; crash → visibility timeout → redelivery.
- Never publish empty batches / never launch empty workers.
- Max attempts = 2; stale `SENDING` → `SKIPPED` (same WA policy as today).

## Migration note

User runs `makemigrations` / `migrate` for `WhatsAppOutbox`. Deploy CDK for queue + scheduler after app ships.
