from pathlib import Path
import ast,compileall,re
root=Path(__file__).resolve().parent.parent
modules=list(root.rglob('*.py'))
errors=[]
for path in modules:
 try: ast.parse(path.read_text())
 except Exception as e: errors.append((str(path.relative_to(root)),str(e)))
assert not errors,errors
must={
 'wearables/migrations/0001_initial.py':['class Migration(', 'name="HealthObservation"','is_current'],
 'wearables/services/ingestion.py':['document_identity_digest','ignore_conflicts=True','is_current=False','remap_member_local_days'],
 'wearables/services/analytics.py':['health_cache_key','caches["health"]','"gaps": gaps','member_today','current_start = latest_day - timedelta(days=6)'],
 'wearables/views.py':['class DeviceRetrySyncView','dashboard_payload'],
 'wearables/device_urls.py':['retry-sync/'],
 'wearables/tests/test_phase1_regression.py':['test_higher_document_version','test_timezone_remap','test_dashboard_cache'],
 'wearables/management/commands/health_phase1_status.py':['class Command'],
}
for rel,needles in must.items():
 s=(root/rel).read_text()
 for n in needles:
  assert n in s,(rel,n)
models=(root/'wearables/models.py').read_text()
indices=re.findall(r'models\.Index\([\s\S]*?name="([^"]+)"\)',models)
assert len(indices)==len(set(indices)),indices
migration=(root/'wearables/migrations/0001_initial.py').read_text()
assert migration.count('migrations.CreateModel(')==10
assert 'DjangoJSONEncoder' in migration
assert compileall.compile_dir(root,quiet=1)
print('PASS: AST/compileall of',len(modules),'Python files')
print('PASS: Phase 1 critical source paths and migration declarations')
print('PASS: no duplicate explicitly named indexes')
print('RUNTIME UNVERIFIED: Requires Python 3.14, Django dependencies, PostgreSQL 17 and ROOK credentials')
