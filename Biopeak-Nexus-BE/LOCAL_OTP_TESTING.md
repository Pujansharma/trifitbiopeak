# Local fixed-OTP test accounts

This is a **local-development-only** convenience. The fixed OTP is `123456` and is accepted only for the eight phone numbers allowlisted in `core/settings/development.py`. The setting is opt-in and defaults to disabled. Do not enable it on Render, staging, or production.

## Enable locally

Set this in your local environment (not Render):

```env
LOCAL_TEST_OTP_ENABLED=true
```

Run with the development settings module, and create the test accounts against your development database:

```bash
python manage.py create_test_mobile_accounts
```

Use the phone numbers configured in `LOCAL_TEST_OTP_PHONES` (currently `+919000000001` through `+919000000008`). These are reserved examples; replace them with eight phone numbers you control if they are invalid for your local phone field validation or conflict with existing database records. The generated email addresses use the reserved `.invalid` domain.

## API test

Base URL locally: `http://127.0.0.1:8000` (adjust to your server port).

1. `POST /auth/request-otp/` JSON body: `{"phone":"+919000000001","purpose":"0"}`
2. `POST /auth/login-otp/` JSON body: `{"phone":"+919000000001","otp":"123456"}`

The login response uses the project's existing token contract and returns `access` and `refresh` JWT values. Use the returned access token as `Authorization: Bearer <access>`.

## Security notes

- `LOCAL_TEST_OTP_ENABLED` defaults to `false`; enable it only in a local environment.
- Both `DEBUG=True` and the explicit setting are required, and the bypass is restricted to the eight allowlisted phone numbers and login purpose.
- Do not set `LOCAL_TEST_OTP_ENABLED=true` in Render. For Render testing, use the normal OTP provider flow, or create a separately access-restricted staging setup with real OTP delivery.
- The existing `/auth/login-phone-direct/` endpoint is separate from this feature and should not be exposed in production without appropriate authentication controls.
