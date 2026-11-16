import base64
from hashlib import sha256
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from django.core.cache import caches
from django.core.cache.backends.dummy import DummyCache
from django.core.cache.backends.locmem import LocMemCache
from redis.exceptions import RedisError

from core.utils.log import logger
from django.utils import timezone
from wearables.services.provider_errors import RookConfigurationError, RookServiceError, RookRequestDeferred
from wearables.services.rate_limit import reserve_provider_request, block_provider_requests
from wearables.services.rate_policy import retry_after_time
from wearables.services.runtime import integer_setting


def shared_summary_cache():
    cache = caches["health"]
    return None if isinstance(cache, (DummyCache, LocMemCache)) else cache


def summary_cache_key(*, base_url: str, client_uuid: str, rook_user_id: str,
                      health_pillar: str, summary_date: str):
    digest = sha256(f"{base_url}:{client_uuid}:{rook_user_id}:{health_pillar}:{summary_date}".encode()).hexdigest()
    return f"rook:summary:v1:{digest}"


def authorized_source_names(payload: Any) -> set[str]:
    if not isinstance(payload, dict):
        return set()
    sources = payload.get("data_sources")
    if not isinstance(sources, list):
        return set()
    return {
        str(source.get("data_source"))
        for source in sources
        if isinstance(source, dict)
        and source.get("authorized") is True
        and source.get("data_source")
    }


def configured_authorization_hosts() -> set[str]:
    """Exact, deployment-approved authorizer hosts (never implicit trust)."""
    configured_hosts = getattr(settings, "ROOK_AUTHORIZATION_ALLOWED_HOSTS", []) or []
    if isinstance(configured_hosts, str):
        configured_hosts = configured_hosts.split(",")
    return {
        str(host).strip().lower()
        for host in configured_hosts
        if str(host).strip()
    }


def require_authorization_hosts(data_source: str) -> set[str]:
    """Fail before changing a connection if OAuth hosts are misconfigured."""
    trusted_hosts = configured_authorization_hosts()
    if not trusted_hosts:
        raise RookServiceError(
            "ROOK_AUTHORIZATION_ALLOWED_HOSTS is not configured; "
            "untrusted authorization host blocked.",
            status_code=503,
        )
    if data_source == "Garmin" and "connect.garmin.com" not in trusted_hosts:
        raise RookServiceError(
            "Garmin authorization requires connect.garmin.com in "
            "ROOK_AUTHORIZATION_ALLOWED_HOSTS.",
            status_code=503,
        )
    return trusted_hosts


def validate_authorization_url(data_source: str, value: Any) -> str | None:
    if not value:
        return None
    if not isinstance(value, str):
        raise RookServiceError("ROOK returned an invalid authorization URL.")
    try:
        parsed = urlparse(value)
        invalid_port = parsed.port is not None
    except ValueError as error:
        raise RookServiceError(
            "ROOK returned an invalid authorization URL."
        ) from error
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or invalid_port
    ):
        raise RookServiceError("ROOK returned an unsafe authorization URL.")
    # ROOK/provider redirects are untrusted input. Never accept arbitrary
    # HTTPS origins when the deployment forgot to configure its allowlist.
    trusted_hosts = require_authorization_hosts(data_source)
    if parsed.hostname not in trusted_hosts:
        # Log only the hostname, not the full URL (which may contain OAuth codes).
        logger.warning(
            f"ROOK authorizer rejected hostname {parsed.hostname!r} "
            f"for {data_source}; verify the provider before changing the allowlist."
        )
        raise RookServiceError("ROOK returned an untrusted authorization host.")
    # Keep Garmin's additional provider-specific host pinning.
    if data_source == "Garmin" and parsed.hostname != "connect.garmin.com":
        logger.warning(
            f"ROOK Garmin authorizer rejected hostname {parsed.hostname!r}."
        )
        raise RookServiceError("ROOK returned an untrusted Garmin URL.")
    return value


class RookClient:
    def __init__(self):
        self.base_url = getattr(settings, "ROOK_BASE_URL", "").rstrip("/")
        self.client_uuid = getattr(settings, "ROOK_CLIENT_UUID", "")
        self.secret_key = getattr(settings, "ROOK_SECRET_KEY", "")
        self.connect_timeout = getattr(settings, "ROOK_CONNECT_TIMEOUT_SECONDS", 5)
        self.read_timeout = getattr(settings, "ROOK_READ_TIMEOUT_SECONDS", 12)

    def ensure_configured(self) -> None:
        if not self.base_url or not self.client_uuid or not self.secret_key:
            raise RookConfigurationError("ROOK credentials are not configured.")

    def authentication_headers(self) -> dict[str, str]:
        self.ensure_configured()
        credentials = base64.b64encode(
            f"{self.client_uuid}:{self.secret_key}".encode()
        ).decode("ascii")
        return {
            "Authorization": f"Basic {credentials}",
            "Accept": "application/json",
        }

    def before_request(self):
        self.ensure_configured()
        reserve_provider_request(self.base_url, self.client_uuid)

    def check_response(self, response):
        if response.status_code == 429:
            retry_at = retry_after_time(response.headers.get("Retry-After"), now=timezone.localtime())
            block_provider_requests(self.base_url, self.client_uuid, retry_at)
            raise RookRequestDeferred(retry_at, reason="provider_429")
        if response.status_code >= 400:
            # Do not log URLs: ROOK authorizer paths contain member identifiers.
            logger.warning(f"ROOK request failed with HTTP {response.status_code}.")
            raise RookServiceError(
                f"ROOK request failed with HTTP {response.status_code}.", status_code=response.status_code,
            )

    def request_json(
        self,
        method: str,
        url: str,
        *,
        json_body: dict | None = None,
        parameters: dict | None = None,
    ) -> dict:
        self.before_request()
        try:
            response = requests.request(
                method,
                url,
                headers=self.authentication_headers(),
                json=json_body,
                params=parameters,
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.RequestException as error:
            raise RookServiceError(
                "ROOK could not be reached. Please retry."
            ) from error
        self.check_response(response)
        if response.status_code == 204 or not response.content:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise RookServiceError("ROOK returned invalid JSON.") from error
        if not isinstance(payload, dict):
            raise RookServiceError("ROOK returned an invalid response.")
        return payload

    def get_processed_summaries(
        self,
        *,
        rook_user_id: str,
        health_pillar: str,
        summary_date: str,
    ) -> list[dict]:
        self.ensure_configured()
        # Optional cross-worker reuse reduces duplicate member/date fetches
        # across provider jobs. Dummy/LocMem deployments retain direct pulls.
        cache = shared_summary_cache()
        cache_key = summary_cache_key(base_url=self.base_url, client_uuid=self.client_uuid,
                                      rook_user_id=rook_user_id, health_pillar=health_pillar,
                                      summary_date=summary_date)
        if cache is not None:
            try:
                cached = cache.get(cache_key)
            except (OSError, RedisError):
                cached = None
            if isinstance(cached, list) and cached and all(isinstance(item, dict) for item in cached):
                return cached
        url = f"{self.base_url}/v2/processed_data/{health_pillar}_health/summary"
        self.before_request()
        try:
            response = requests.get(
                url,
                headers=self.authentication_headers(),
                params={"user_id": rook_user_id, "date": summary_date},
                timeout=(self.connect_timeout, self.read_timeout),
            )
        except requests.RequestException as error:
            raise RookServiceError(
                "ROOK recovery data could not be reached."
            ) from error
        # Empty 401/429/500 responses are failures, not successful no-data pulls.
        self.check_response(response)
        if response.status_code == 204 or not response.content:
            return []
        try:
            payload = response.json()
        except ValueError as error:
            raise RookServiceError("ROOK returned invalid recovery JSON.") from error
        documents = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(document, dict) for document in documents):
            raise RookServiceError("ROOK returned invalid recovery documents.")
        if cache is not None and documents:
            try:
                cache.set(cache_key, documents, timeout=integer_setting(
                    "ROOK_SUMMARY_CACHE_SECONDS", 15, minimum=1, maximum=60,
                ))
            except (OSError, RedisError):
                logger.warning("ROOK summary cache unavailable; direct pulls remain enabled.")
        return documents

    def get_authorizer(
        self,
        *,
        rook_user_id: str,
        data_source: str,
        redirect_url: str | None = None,
    ) -> dict:
        url = (
            f"{self.base_url}/api/v1/user_id/{rook_user_id}/"
            f"data_source/{data_source}/authorizer"
        )
        parameters = {"redirect_url": redirect_url} if redirect_url else None
        payload = self.request_json("GET", url, parameters=parameters)
        authorization_url = validate_authorization_url(
            data_source,
            payload.get("authorization_url") or payload.get("authorizer_url"),
        )
        return {
            "data_source": data_source,
            "authorized": payload.get("authorized") is True,
            "authorization_url": authorization_url,
        }

    def get_authorized_sources(self, *, rook_user_id: str) -> set[str]:
        url = (
            f"{self.base_url}/api/v2/user_id/{rook_user_id}/"
            "data_sources/authorized"
        )
        return authorized_source_names(self.request_json("GET", url))

    def revoke_source(self, *, rook_user_id: str, data_source: str) -> None:
        url = (
            f"{self.base_url}/api/v1/user_id/{rook_user_id}/"
            "data_sources/revoke_auth"
        )
        self.request_json("POST", url, json_body={"data_source": data_source})
