# ROOK PR review fixes — 2026-11-17

Scope: reviewer P1/P2 corrections only. No production service, device API, worker, or database migration behavior was changed.

## Changes

1. **Bruno (P1):** Renamed the health requests to `GET Domain Summary.bru` and `GET Domain Summary Detail.bru`, and updated URLs to `/api/v1/health/domain-summary/` and `/api/v1/health/domain-summary/{{rook_health_domain}}/?days=30`. Deleted `GET Timeline.bru` because the route is removed. Updated the Bruno health folder description.
2. **Obsolete tests (P1):** Removed imports and assertions for deleted `wearables.services.job_selection`. Tests now exercise `enqueue_or_reuse_fetch_rook_data_job` for recovery cooldown and coalescing, and `eligible_nightly_connections` / `run_rook_sync_scan` for the seven-day nightly rule. Also replaced the removed `enqueue_health_freshness_checks` management-command call with the current scan.
3. **Project memory (P2):** Corrected the retired health timeline reference and the retired webhook/document ingestion statement in `docs/MEMORY.md`.
4. **Docs location (P2):** Moved `MERGE_NOTES_REMOVE_ROOK_TABLES.md` to `docs/` without changing its content.

## Execute in the actual project environment

The project requires Python 3.14, Django 6 and a PostgreSQL test database. Run:

```powershell
uv run python manage.py check
uv run python manage.py test wearables.tests.test_pr143_cooldown_atomic_indexes wearables.tests.test_pr143_queue_redis_followup wearables.tests.test_device_api_contract_refactor -v 2
uv run python manage.py test wearables.tests -v 2
```

Then run the two Bruno requests with an authorized customer token. The timeline endpoint is intentionally absent. No API routes, tables, workers or migrations were modified by this patch.

## Reviewer replies (after tests pass)

- Bruno: Updated Bruno requests for the new domain-summary routes and removed the old timeline request.
- Deleted selector: Reworked PR143 tests for the current nightly scheduler and queue deduplication/cooldown behavior; removed the deleted command call.
- MEMORY: Corrected documentation to match the retired timeline and current API-fetch data path.
- Merge note: Moved the merge notes under docs/ as required.
