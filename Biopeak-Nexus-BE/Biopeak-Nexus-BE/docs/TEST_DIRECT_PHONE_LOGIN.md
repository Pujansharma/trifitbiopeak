# Restricted eight-account phone login for development/staging

**The former unprotected direct-login procedure is superseded.** Use the full walkthrough in [`STAGING-TEST-ACCOUNTS-AIVEN-RENDER.md`](STAGING-TEST-ACCOUNTS-AIVEN-RENDER.md).

The synthetic phone-only shortcut is disabled in production, requires a strong `X-Test-Login-Key`, is limited to the eight allowlisted synthetic customer identities, and must run only against an isolated test database. Do not use it in the published mobile app.
