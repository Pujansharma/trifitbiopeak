"""Static source and migration checks (not a substitute for Django integration tests)."""
from pathlib import Path
import ast
import re

ROOT = Path(__file__).resolve().parent.parent
errors = []
for path in ROOT.rglob("*.py"):
    if ".venv" in path.parts:
        continue
    try:
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (SyntaxError, UnicodeError) as error:
        errors.append(f"{path.relative_to(ROOT)}: {error}")
assert not errors, "\n".join(errors)

checks = {
    "core/api/urls.py": ('include("wearables.device_urls")', 'include("wearables.health_urls")'),
    "webhooks/urls.py": ('include("webhooks.rook.urls")',),
    "core/settings/base.py": ('"wearables"', '"wearable_connect"', '"health_read"', 'CACHES'),
    "wearables/views.py": ('class DeviceRetrySyncView', 'dashboard_payload'),
    "wearables/device_urls.py": ('retry-sync/',),
    "wearables/services/job_processor.py": ('customer_profile_id=customer_profile_id',),
    "wearables/migrations/0001_initial.py": ('0020_customerprofilefeature_wearables_tab',),
}
for name, phrases in checks.items():
    content = (ROOT / name).read_text()
    for phrase in phrases:
        assert phrase in content, f"Missing {phrase} in {name}"

assert not (ROOT / "accounts/customers/migrations/0020_customerprofile_height_cm_weight_kg.py").exists()
assert 'height_cm = models.FloatField' not in (ROOT / 'accounts/customers/models.py').read_text()
assert (ROOT / 'accounts/organizations/migrations/0003_platformfeature_wearables_tab.py').exists()
assert (ROOT / 'accounts/customers/migrations/0020_customerprofilefeature_wearables_tab.py').exists()

print("PASS: Python AST compilation, mandatory routes/settings, feature-choice migrations, scoped worker filter")
print("NOTE: This DOES NOT test Django migrations, database, live ROOK, or PRD E2E")
