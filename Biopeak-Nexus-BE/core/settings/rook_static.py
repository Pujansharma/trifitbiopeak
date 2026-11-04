"""Non-secret ROOK defaults reviewed for the BioPeak integration.

These are source-controlled deployment choices, NOT proof that ROOK granted
provider or historical-import entitlements. Verify with ROOK before GA.
Change these lists through code review when provider approvals change.
"""

# Keep the existing API/SDK history caps in serializers and connection services.
ROOK_HISTORICAL_DAYS_DEFAULT = 7

# Exact HTTPS authorizer hostnames from the project's latest DEV configuration.
# Never use wildcard hosts or allow arbitrary HTTPS redirects.
ROOK_AUTHORIZATION_HOSTS = (
    "connect.garmin.com",
    "www.fitbit.com",
    "cloud.ouraring.com",
    "developer.ouraring.com",
    "api.prod.whoop.com",
    "flow.polar.com",
    "auth.polar.com",
    "account.withings.com",
    "api.dexcom.com",
    "sandbox-api.dexcom.com",
)

# This is the list from the latest local DEV settings. Confirm that each
# provider is actually enabled for the staging/production ROOK account.
ROOK_PROVISIONED_SOURCE_NAMES = (
    "Garmin",
    "Fitbit",
    "Oura",
    "Whoop",
    "Polar",
    "Withings",
    "Dexcom",
    "Apple Health",
    "Health Connect",
    "Samsung Health",
)
