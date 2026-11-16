# WhatsApp background jobs — cost estimates (ap-south-1)

Estimates for **SQS + Lambda launcher + Fargate worker** (0.25 vCPU / 1 GB).  
List prices researched ~Nov 2026; verify on AWS Pricing before budgeting. Free tier ignored (conservative).

## Unit rates used

| Service | Rate |
|---------|------|
| Lambda requests | $0.20 / million |
| Lambda compute (x86) | $0.0000166667 / GB-second |
| Fargate Linux x86 | $0.04256 / vCPU-hour + $0.004655 / GB-hour |
| SQS Standard | ~$0.40 / million requests (first band) |

Fargate **0.25 vCPU + 1 GB** ≈ **$0.0153 / hour** ≈ **$0.000255 / task-minute** (1-minute minimum billing).

Lambda launcher assumption: **256 MB**, **500 ms** → **0.125 GB-s** per invoke.

## Monthly cost at 1,000–5,000 events/day

“Event” = one `WhatsAppOutbox` send attempt.  
With batch size 10, Fargate/Lambda launches ≈ `ceil(events / 10)` in the steady batched case; worst case = 1 event per message.

### Batched (≤10 ids/message) — expected production

| Events/day | ~Launches/day | Lambda $/mo | Fargate $/mo (1 min/task) | SQS $/mo | **Total $/mo** |
|------------|---------------|-------------|---------------------------|----------|----------------|
| 1,000 | ~100 | &lt; $0.10 | ~$0.80 | &lt; $0.50 | **~$1–2** |
| 2,000 | ~200 | &lt; $0.20 | ~$1.50 | &lt; $0.50 | **~$2–3** |
| 5,000 | ~500 | &lt; $0.50 | ~$4 | &lt; $1 | **~$5–6** |

If each task averages **2 minutes** (cold start + Meta): multiply Fargate ≈ ×2 → **~$2–12/mo** across the same range.

### Worst case (1 SQS message per event)

| Events/day | Launches/day | Lambda $/mo | Fargate $/mo (1 min) | **Total $/mo** |
|------------|--------------|-------------|----------------------|----------------|
| 1,000 | 1,000 | ~$0.50 | ~$8 | **~$9–10** |
| 2,000 | 2,000 | ~$1 | ~$15 | **~$16–18** |
| 5,000 | 5,000 | ~$2.50 | ~$38 | **~$40–45** |

## What dominates

1. **Fargate task-minutes** (not Lambda).  
2. Batching (≤10) cuts Fargate ~10× vs 1-id messages.  
3. Lambda at 5k events/day stays **well under $5/mo**.  
4. SQS is noise at this volume (often inside free tier).

## Not included

- NAT Gateway / data transfer (shared with API VPC — usually dominates idle infra if NAT is dedicated)  
- CloudWatch Logs storage  
- Meta WhatsApp API fees  
- EventBridge Scheduler (pennies for 15‑min cron)

## Ack note (cost-relevant)

Lambda event-source mapping deletes the SQS message after **successful RunTask**.  
Crashed workers are recovered via `QUEUED`→`PENDING` reclaim + `run_whatsapp_reminder_schedule` re-dispatch — may add a small extra Fargate/SQS retry cost, still small at 1k–5k/day.
