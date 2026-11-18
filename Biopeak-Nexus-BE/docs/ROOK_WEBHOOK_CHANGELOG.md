# ROOK webhook change list

Added:
- `bruno/webhooks/rook/POST Data.bru`
- `bruno/webhooks/rook/POST Notification.bru`
- `bruno/webhooks/rook/folder.bru`
- `docs/ROOK_WEBHOOK_RESTORED.md`
- `wearables/tests/test_rook_webhooks.py`
- `webhooks/rook/__init__.py`
- `webhooks/rook/urls.py`
- `webhooks/rook/views.py`

Modified:
- `.env.example`
- `core/settings/base.py`
- `docs/MEMORY.md`
- `wearables/management/commands/check_rook_configuration.py`
- `wearables/services/signature.py`
- `wearables/tests/test_rook_deployment_configuration.py`
- `wearables/tests/test_signature.py`
- `webhooks/urls.py`


No new database model or migration added.

Latest scope update (18 November 2026): `POST Notification.bru` removed; ROOK notification webhook HTTP route and handler removed, only Data Webhook remains. No database changes. The preceding list documents the earlier restoration artifact.
