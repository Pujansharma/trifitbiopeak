from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.conf import settings
from rest_framework import serializers

from core.utils.serializers import BaseSerializer
from wearables.utils.constants import (
    HEALTH_DOMAIN_ORDER,
    NATIVE_WEARABLE_SOURCES,
    HistoricalImportStatus,
    PermissionStatus,
    PreferredUnits,
    WearableSource,
)


class DeviceConnectSerializer(BaseSerializer):
    data_source = serializers.ChoiceField(choices=WearableSource.choices)
    consent_accepted = serializers.BooleanField(write_only=True)
    consent_version = serializers.CharField(max_length=32, default="v1")
    historical_days = serializers.IntegerField(min_value=0, max_value=29, required=False)
    redirect_url = serializers.URLField(required=False, allow_blank=False)
    timezone_name = serializers.CharField(max_length=64, required=False)
    preferred_units = serializers.ChoiceField(
        choices=PreferredUnits.choices,
        required=False,
    )

    def validate(self, attrs):
        source = attrs.get("data_source")
        # The ROOK v1 per-source authorizer documents seven supported API sources.
        # Strava is a future/conditional option but is not accepted by that API.
        if source == WearableSource.STRAVA:
            raise serializers.ValidationError({
                "data_source": "Strava authorization is not supported by the configured ROOK authorizer API."
            })
        # ROOK supports up to 7 days for API providers (e.g. Garmin), or
        # 29 days for native SDK sources. A valid client request for a longer
        # window must never be interpreted as permission to fetch more data.
        # Cap it to the supported window, and expose the adjustment in the
        # connection response rather than silently claiming a 29-day import.
        max_days = 29 if source in NATIVE_WEARABLE_SOURCES else 7
        requested = attrs.get(
            "historical_days",
            min(getattr(settings, "ROOK_HISTORICAL_DAYS", 7), max_days),
        )
        self.requested_historical_days = requested
        self.max_historical_days = max_days
        # The PRD disables pre-existing ROOK imports by default in production.
        # Operators must explicitly opt in after configuring ROOK's add-on.
        from wearables.services.config import preexisting_import_enabled, provisioned_sources
        enabled = preexisting_import_enabled()
        self.history_disabled_by_policy = not enabled
        attrs["historical_days"] = min(requested, max_days) if enabled else 0
        configured_sources = provisioned_sources()
        # The catalogue is intentionally fail-closed when the operator has
        # not supplied ROOK_PROVISIONED_SOURCES. The connect endpoint must
        # make the same decision rather than allowing an unprovisioned OAuth.
        if configured_sources is None:
            raise serializers.ValidationError({
                "data_source": "ROOK provider provisioning has not been configured."
            })
        if source not in configured_sources:
            raise serializers.ValidationError({
                "data_source": "This provider is not provisioned for the ROOK developer account."
            })
        return attrs

    def validate_redirect_url(self, value):
        # In production OAuth is returned through the server-owned stateful
        # callback. Without it, permit mobile redirect hosts explicitly
        # allowlisted by the operator; no untrusted open redirects.
        from urllib.parse import urlsplit
        parsed = urlsplit(value)
        if len(value) > 50:
            raise serializers.ValidationError("ROOK redirect URLs must be at most 50 characters.")
        allowed = set(getattr(settings, "ROOK_MOBILE_REDIRECT_ALLOWED_HOSTS", []))
        if not getattr(settings, "ROOK_CALLBACK_URL", "") and (
            parsed.scheme != "https" or parsed.hostname not in allowed
            or parsed.username or parsed.password or parsed.fragment
        ):
            raise serializers.ValidationError("Redirect URL is not allowlisted for ROOK authorization.")
        return value

    def validate_consent_accepted(self, value):
        if value is not True:
            raise serializers.ValidationError(
                "Wearable ingestion and longitudinal storage consent is required."
            )
        return value

    def validate_timezone_name(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise serializers.ValidationError("Unknown timezone.") from error
        return value


class DeviceDisconnectSerializer(BaseSerializer):
    data_source = serializers.ChoiceField(choices=WearableSource.choices)


class NativeDeviceStatusSerializer(BaseSerializer):
    data_source = serializers.ChoiceField(
        choices=[(source, source) for source in sorted(NATIVE_WEARABLE_SOURCES)]
    )
    sdk_linked = serializers.BooleanField()
    permission_status = serializers.ChoiceField(choices=PermissionStatus.choices)
    capabilities = serializers.ListField(
        child=serializers.ChoiceField(choices=[(domain, domain) for domain in HEALTH_DOMAIN_ORDER]),
        required=False,
        allow_empty=True,
    )
    timezone_name = serializers.CharField(max_length=64, required=False)
    historical_days = serializers.IntegerField(
        min_value=0,
        max_value=29,
        required=False,
    )
    historical_import_status = serializers.ChoiceField(
        choices=HistoricalImportStatus.choices, required=False,
    )

    def validate_timezone_name(self, value):
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as error:
            raise serializers.ValidationError("Unknown timezone.") from error
        return value


class DomainQuerySerializer(BaseSerializer):
    # `days` remains backward compatible. `window=lifetime` permits the
    # complete retained timeline without an arbitrary 365-day restriction.
    days = serializers.IntegerField(min_value=1, max_value=365, default=90)
    window = serializers.ChoiceField(
        choices=("7d", "14d", "30d", "90d", "lifetime"), required=False,
    )


class TimelineQuerySerializer(BaseSerializer):
    start = serializers.DateField(required=False)
    end = serializers.DateField(required=False)
    domain = serializers.ChoiceField(
        choices=[(domain, domain) for domain in HEALTH_DOMAIN_ORDER],
        required=False,
    )
    offset = serializers.IntegerField(min_value=0, default=0)
    limit = serializers.IntegerField(min_value=1, max_value=200, default=50)

    def validate(self, attributes):
        start = attributes.get("start")
        end = attributes.get("end")
        if start and end and end < start:
            raise serializers.ValidationError("End date must be on or after start date.")
        return attributes

