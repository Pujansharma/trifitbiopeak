# Eight local direct-phone login accounts

Run only against an isolated local/development PostgreSQL database, never against production or shared real-client databases.

```bash
python manage.py migrate
python manage.py seed_direct_login_test_users
```

This command is idempotent (safe to rerun), requires `core.settings.development` with `DEBUG=True`, creates a User, Customer, primary CustomerProfile and CUSTOMER account type for each number, and leaves the authentication endpoints unchanged.

| Test account | Phone |
| --- | --- |
| Test 01 | +919999900101 |
| Test 02 | +919999900102 |
| Test 03 | +919999900103 |
| Test 04 | +919999900104 |
| Test 05 | +919999900105 |
| Test 06 | +919999900106 |
| Test 07 | +919999900107 |
| Test 08 | +919999900108 |

Example:
```bash
curl -X POST http://127.0.0.1:8000/auth/login-phone-direct/ \
  -H 'Content-Type: application/json' \
  -d '{"phone":"+919999900101"}'
```

Expected success: `data.access` and `data.refresh` tokens. No OTP is needed for this endpoint.

**Security:** `/auth/login-phone-direct/` already bypasses OTP for any registered active phone. It must be disabled/removed outside isolated testing, because the original API does not restrict use to these eight numbers. The seed command does not change that existing behavior.

These accounts do not automatically have centers, programs, bookings, or wearable integrations assigned; those must be provisioned separately to test dependent features.
