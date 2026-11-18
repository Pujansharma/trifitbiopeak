# Merge notes: removing RookHealthDocument and HealthObservation on the final branch

Base: `Biopeak-Nexus-BErefactor-ROOK-APIs-Updated` (final refactor branch).

## Applied on top of the final branch
- `wearables/models.py`: removed `RookHealthDocument` and `HealthObservation`; added receipt identity fields and
  summary `contributions` / `data_sources`; removed `RookOutbox.document`.
- `wearables/services/ingestion.py` (rewritten, same public names and response keys) and new
  `wearables/services/daily_contributions.py`.
- `wearables/services/analytics.py`, `timeline.py`, `progress.py`, `job_queue.py`, `job_claims.py`,
  `job_processor.py`, `admin.py`.
- `wearables/services/observation_values.py` deleted.
- Migrations `0006_rook_receipts_daily_contributions.py` and `0007_remove_rookhealthdocument_healthobservation.py`.
- Tests updated to the new model: `test_ingestion`, `test_phase1_regression`, `test_phase1_improvements`,
  `test_phase1_completion`, `test_phase1_release_safety`, `test_prd_gap_closure`, `test_client_safe_integration`,
  `test_pr_review_12_fixes`.

## Not applied (files your branch already removed)
- `wearables/services/job_selection.py` (orphan-recovery sweep)
- `wearables/management/commands/health_phase1_status.py`
- `wearables/management/commands/recompute_health_algorithm.py`

## Pre-existing issues in the final branch (not caused by this change)
- `wearables/tests/test_pr143_queue_redis_followup.py` and `test_pr143_cooldown_atomic_indexes.py` import
  `wearables.services.job_selection`, which the branch no longer contains. These modules cannot be imported.
- With the sweep removed, a receipt queued by the recovery path (`enqueue_normalization=False`) is only finished
  when recovery calls `normalize_health_document` again. Nothing else picks up stranded `QUEUED` receipts. Decide
  whether to restore a sweeper.

## Verification
- Import check across the whole project: every `from wearables.* import name` resolves (Python 3.14 files
  were skipped by the 3.12 checker only).
- Not executed: Django check, migrations, and test suite. Run them as described in the change report.
