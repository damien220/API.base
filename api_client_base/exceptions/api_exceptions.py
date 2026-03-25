"""API-specific exception hierarchy."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..request.models import APIRequest, APIResponse


class APIClientError(Exception):
    """Base exception for all API client errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        request: Optional[APIRequest] = None,
        response: Optional[APIResponse] = None,
        retry_eligible: bool = False,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.request = request
        self.response = response
        self.retry_eligible = retry_eligible
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        """Return a structured dictionary representation."""
        result: Dict[str, Any] = {
            "error": self.__class__.__name__,
            "message": self.message,
        }
        if self.status_code is not None:
            result["status_code"] = self.status_code
        if self.details:
            result["details"] = self.details
        return result


class AuthenticationError(APIClientError):
    """401 — Invalid or expired credentials."""

    def __init__(self, message: str = "Authentication failed", **kwargs: Any) -> None:
        super().__init__(message, status_code=401, retry_eligible=False, **kwargs)


class AuthorizationError(APIClientError):
    """403 — Insufficient permissions."""

    def __init__(self, message: str = "Forbidden", **kwargs: Any) -> None:
        super().__init__(message, status_code=403, retry_eligible=False, **kwargs)


class NotFoundError(APIClientError):
    """404 — Resource not found."""

    def __init__(self, message: str = "Resource not found", **kwargs: Any) -> None:
        super().__init__(message, status_code=404, retry_eligible=False, **kwargs)


class ValidationError(APIClientError):
    """400/422 — Bad request data."""

    def __init__(self, message: str = "Validation error", **kwargs: Any) -> None:
        super().__init__(message, status_code=400, retry_eligible=False, **kwargs)


class RateLimitError(APIClientError):
    """429 — Rate limit exceeded."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: Optional[float] = None,
        limit: Optional[int] = None,
        remaining: Optional[int] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(message, status_code=429, retry_eligible=True, **kwargs)
        self.retry_after = retry_after
        self.limit = limit
        self.remaining = remaining

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.retry_after is not None:
            result["retry_after"] = self.retry_after
        if self.limit is not None:
            result["limit"] = self.limit
        if self.remaining is not None:
            result["remaining"] = self.remaining
        return result


class ServerError(APIClientError):
    """5xx — Upstream service failure."""

    def __init__(
        self, message: str = "Server error", *, status_code: int = 500, **kwargs: Any
    ) -> None:
        super().__init__(message, status_code=status_code, retry_eligible=True, **kwargs)


class APITimeoutError(APIClientError):
    """Request timed out."""

    def __init__(self, message: str = "Request timed out", **kwargs: Any) -> None:
        super().__init__(message, retry_eligible=True, **kwargs)


class APIConnectionError(APIClientError):
    """Network unreachable / DNS failure."""

    def __init__(self, message: str = "Connection failed", **kwargs: Any) -> None:
        super().__init__(message, retry_eligible=True, **kwargs)


class CircuitOpenError(APIClientError):
    """Circuit breaker is open, request rejected."""

    def __init__(
        self, message: str = "Circuit breaker is open", **kwargs: Any
    ) -> None:
        super().__init__(message, retry_eligible=False, **kwargs)


class ResponseParsingError(APIClientError):
    """Failed to parse response body."""

    def __init__(
        self, message: str = "Failed to parse response", **kwargs: Any
    ) -> None:
        super().__init__(message, retry_eligible=False, **kwargs)
