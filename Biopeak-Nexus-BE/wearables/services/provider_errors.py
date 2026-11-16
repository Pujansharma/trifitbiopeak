"""Sanitized provider failures shared by the HTTP adapter and worker dispatcher."""
from datetime import datetime


class RookConfigurationError(RuntimeError):
    pass


class RookServiceError(RuntimeError):
    def __init__(self, detail: str, *, status_code: int = 502):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


class RookRequestDeferred(RookServiceError):
    def __init__(self, retry_at: datetime, *, reason: str = "provider_budget"):
        super().__init__("ROOK synchronization is waiting for its approved request budget.", status_code=429)
        self.retry_at = retry_at
        self.reason = reason
