# PR #143: final audit of seven reviewer findings

**Scope:** Four newer P1 findings (worker priority/retry reuse, authorization URL host allowlist, OAuth transaction boundary, timeline pagination) and three earlier findings (native SDK credential distribution, multi-worker health caching, timezone remapping). The audit starts from `Biopeak-Nexus-BE-PR143-Older-Review-Safety-Verified-Full.zip`.

## Code status

| Finding | Code status | Operational condition |
| --- | --- | --- |
| Job priority and duplicate recovery | Implemented. Normalization first, one recovery per sweep, shared open-recovery reuse. This audit also reserves one recovery slot if freshness jobs would otherwise exhaust the sweep. | Exercise scheduled sweeps against a PostgreSQL queue containing realistic job volumes. |
| Authorization host allowlist | Implemented; reject empty lists, unknown hosts, non-HTTPS, and nonstandard ports. | Configure approved exact hostnames in every environment. |
| OAuth transaction | Implemented; network request precedes the short atomic claim/state transition. | Exercise concurrent callbacks and delayed ROOK responses in staging. |
| Timeline bounds | Implemented; maximum offset=1000, limit=200; wearable/clinical querysets sliced before Python merging. | Verify query latency with large test datasets. |
| Native SDK secret | Guarded by consent, native connection eligibility, an explicit default-off distribution flag, and a credential distinct from the server Basic-auth secret. This audit also excludes permission-denied native connections. | Confirm ROOK permits distributing the dedicated, app-bound SDK credential and has independent rotation. Do not enable without approval. |
| Health caching | Shared database HealthDomainSnapshot; process-local health cache disabled via DummyCache. | Django default LocMem still makes DRF throttling per-worker. Require centralized WAF/API Gateway or a shared throttle backend before production GA; test across ECS workers. |
| Timezone remapping | Implemented as 500-observation update transactions with per-day summary rebuilds; original UTC instants are preserved. | Test DST, large histories, concurrent timezone changes and interrupted-job retries on PostgreSQL. |

## Exact changes made in this final audit

- `wearables/services/job_processor.py`: prevent recovery starvation behind a permanently full freshness queue without reducing normalization priority or increasing the one-recovery cap.
- `wearables/views.py`: exclude `permission_denied` native connections from SDK credential eligibility in addition to the previous three disallowed states.
- `wearables/tests/test_pr143_followup_fixes.py`: regression cases for the full-freshness queue and all-normalization queue.
- `wearables/tests/test_older_pr143_security_cache_remap.py`: update SDK-connection expectation for permission-denied states.
- This handover document (new).

No model, migrations, authentication or unrelated business files were edited.

## Tests / deployment gate

```powershell
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py test wearables.tests.test_pr143_followup_fixes
uv run python manage.py test wearables.tests.test_older_pr143_security_cache_remap
uv run python manage.py test wearables.tests.test_pr_review_12_fixes
uv run python manage.py test wearables.tests
uv run python manage.py check_rook_configuration --strict
```

The Django suite requires Python 3.14, installed project dependencies and a safe PostgreSQL test database. The ROOK SDK credential decision and shared rate limiting are release dependencies, not something a local ZIP can certify. This audit does **not** assert that integration tests or live ROOK tests passed.
