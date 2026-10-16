# Reusable system OTPs

System OTPs are configured on individual `PhoneVerification` records using
`is_system`. Each record belongs to one phone and purpose: login (`0`), register (`1`), or verify (`2`). System behavior
applies to all three purposes.

## Admin setup

1. Apply the user-generated migration for the existing `is_system` and
   `lockout_expires_at` model additions if those fields are not already in the
   database. Codex does not generate migrations.
2. Request an OTP to create a record if one does not exist. This first request
   uses ordinary delivery because new records default to `is_system=False`.
   Login-purpose requests require an existing active user.
3. Open Phone verifications in Django admin, locate the phone/purpose record,
   enable **Is system**, and save. Adding records through this admin is disabled.
4. Request an OTP again. Existing credentials are retained; missing secret or
   counter values are initialized. The record is activated without delivery.
5. Open its admin detail page and read **Current OTP**. The display is empty
   when there is no secret. Only `is_system` and `is_active` are editable;
   identifiers, purpose, counters, timestamps, and lockout state are read-only.

The code is available only through the permission-protected admin detail page,
not through the public OTP API. The admin list supports phone/ID search and
purpose, system, and activity filters.

## Runtime behavior

| Behavior                         | Ordinary OTP                                   | System OTP                                                          |
|----------------------------------|------------------------------------------------|---------------------------------------------------------------------|
| Request                          | Regenerates credentials and increments retries | Preserves credentials, initializes missing values, activates record |
| Delivery                         | Existing debug email / SMS / WhatsApp routing  | None, including debug email                                         |
| Resend cooldown                  | Existing checks                                | Bypassed, regardless of retry state                                 |
| Expiry                           | Existing expiry validation                     | Ignored; requests do not change `expires_at`                        |
| Successful login / verify        | Existing credential clearing and deactivation  | Credentials and active status preserved                             |
| Successful register verification | Sets `verified_at` and clears credentials      | Sets `verified_at`, preserving credentials and retry state          |
| Incorrect code                   | Existing rejection                             | Rejected without adding lockouts                                    |

System requests do not increment retries or modify lockout timestamps. No
failed-attempt lockout feature is added. Existing TOTP behavior is unchanged.
Phone, purpose, and account eligibility checks remain in force. General
verification still requires an active record; system login also requires an
active record. OTP requests activate the record as before.

Disabling `is_system` restores ordinary OTP behavior, including expiry checks
and cooldowns. Request a fresh ordinary OTP when the retained expiry has passed.

## API and Bruno

The existing endpoints and envelopes are unchanged:

```http
POST /auth/request-otp/
Content-Type: application/json

{"phone": "+91-9999999999", "purpose": "0"}
```

```json
{
  "detail": "OTP sent successfully."
}
```

This success message also applies to system OTPs even though nothing is sent.

```http
POST /auth/login-otp/
Content-Type: application/json

{"phone": "+91-9999999999", "otp": "123456"}
```

Login returns the existing `detail` and `data` envelope with JWTs. Public callers
cannot enable system mode or retrieve the code. Use **Request OTP** and **Login OTP** in Bruno's Auth folder; set`phone`
and the secret `otp` variable
in the selected environment. No registration/general-verification route is
added; reusable behavior is also implemented in the existing verification
serializer for those purposes.

## Validation

Changes were reviewed statically. No Python commands, tests, or migration
generation were run. Runtime acceptance checks, when explicitly authorized:

- Repeat system requests immediately with stale retry state and expired
  timestamps: the code remains stable, retries/timestamps remain unchanged,
  and no channel sends a message in debug or production mode.
- Request with missing credentials: initialize only missing values.
- Verify an expired system code repeatedly: accept the correct code, preserve
  credentials/activity, and reject an incorrect code without lockout changes.
- Verify a registration-purpose system code: stamp `verified_at` and retain
  the reusable code.
- Confirm ordinary delivery, cooldown, expiry, and consumption remain unchanged.
- Confirm admin permissions, toggles, read-only fields, and empty code display.
