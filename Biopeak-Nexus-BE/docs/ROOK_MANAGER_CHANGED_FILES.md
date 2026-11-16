# ROOK manager-flow changed files

Historical packaging note for the Nov 2026 manager-diagram drop. **Do not treat paths below as current inventory.**

Current execution path (2026-11-16):

- Commands: `process_rook_auth_jobs`, `process_rook_data_fetch_jobs`, `process_pending_rook_sync_scan`
- Infra: `infra/integrations.yaml` only (BackgroundJobsStack); ECS via `manage.py`, not worker `.sh`
- Removed / never ship: `process_health_jobs`, `run_scheduled_worker`, `worker_leases.py`, `worker_shutdown.py`, legacy `assets/infrastructure/rook-*.yml`, `reconcile_rook_jobs`, `assets/scripts/process_rook_*.sh`

Canonical flow doc: `docs/ROOK_MANAGER_FLOWS.md`.
