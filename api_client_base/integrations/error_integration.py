"""Optional integration with Error-Exception_Handler for structured error normalization."""

from __future__ import annotations

from typing import Any, Dict, Optional, Type

from ..exceptions.api_exceptions import (
    APIClientError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

# Attempt to import error_handler — graceful degradation if not installed
try:
    from error_handler import (
        BaseAppException,
        ConflictException,
        ErrorHandler,
        ForbiddenException,
        InternalException,
        NotFoundException,
        UnauthorizedException,
        ValidationException,
    )

    _HAS_ERROR_HANDLER = True
except ImportError:
    _HAS_ERROR_HANDLER = False


def is_available() -> bool:
    """Check if Error-Exception_Handler is installed and importable."""
    return _HAS_ERROR_HANDLER


# Mapping from API exceptions to Error-Exception_Handler exceptions
_ERROR_MAP: Dict[Type[APIClientError], str] = {
    AuthenticationError: "UnauthorizedException",
    AuthorizationError: "ForbiddenException",
    NotFoundError: "NotFoundException",
    ValidationError: "ValidationException",
    ServerError: "InternalException",
}


def normalize_api_error(
    error: APIClientError,
    *,
    api_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Any:
    """Convert an APIClientError into a BaseAppException from Error-Exception_Handler.

    This bridges API-level errors into the project's unified error
    format so that all error handling flows through a single system.

    Args:
        error: The API client error to normalize.
        api_name: Name of the API service (e.g., "openai", "telegram").
        endpoint: Endpoint name for context.

    Returns:
        A BaseAppException subclass instance.

    Raises:
        RuntimeError: If Error-Exception_Handler is not installed.
    """
    if not _HAS_ERROR_HANDLER:
        raise RuntimeError(
            "Error-Exception_Handler is not installed. "
            "Install it to use error normalization."
        )

    # Build details dict
    details: Dict[str, Any] = {}
    if api_name:
        details["api_name"] = api_name
    if endpoint:
        details["endpoint"] = endpoint
    if error.status_code is not None:
        details["status_code"] = error.status_code
    if error.details:
        details["upstream_details"] = error.details

    # Extract upstream error body
    if error.response is not None and error.response.body is not None:
        body = error.response.body
        if isinstance(body, dict):
            details["upstream_body"] = body
        elif isinstance(body, str) and body:
            details["upstream_body"] = body[:500]

    message = str(error)

    # Map to specific exception types
    if isinstance(error, AuthenticationError):
        return UnauthorizedException(message, details=details)

    if isinstance(error, AuthorizationError):
        return ForbiddenException(message, details=details)

    if isinstance(error, NotFoundError):
        return NotFoundException(message, details=details)

    if isinstance(error, ValidationError):
        return ValidationException(message, details=details)

    if isinstance(error, RateLimitError):
        details["retry_after"] = error.retry_after
        details["limit"] = error.limit
        details["remaining"] = error.remaining
        # No direct mapping — use ValidationException with rate limit info
        return ValidationException(
            f"Rate limited: {message}",
            details=details,
        )

    if isinstance(error, ServerError):
        return InternalException(message, details=details)

    # Fallback for any other APIClientError
    return InternalException(
        f"API error: {message}",
        details=details,
    )


def handle_api_error(error: APIClientError) -> Dict[str, Any]:
    """Process an APIClientError through ErrorHandler.handle().

    Returns a dict with 'status_code' and 'body' keys.

    Args:
        error: The API client error.

    Returns:
        Dict with 'status_code' (int) and 'body' (dict) keys.

    Raises:
        RuntimeError: If Error-Exception_Handler is not installed.
    """
    if not _HAS_ERROR_HANDLER:
        raise RuntimeError(
            "Error-Exception_Handler is not installed. "
            "Install it to use error handling."
        )

    normalized = normalize_api_error(error)
    return ErrorHandler.handle(normalized)


def register_api_errors_with_handler() -> None:
    """Register APIClientError as a known type with ErrorHandler.

    After calling this, ``ErrorHandler.handle()`` can directly
    process ``APIClientError`` instances by first normalizing them.

    Raises:
        RuntimeError: If Error-Exception_Handler is not installed.
    """
    if not _HAS_ERROR_HANDLER:
        raise RuntimeError(
            "Error-Exception_Handler is not installed."
        )
    # ErrorHandler already handles BaseAppException subclasses.
    # This function is a no-op hook for future extensibility
    # (e.g., custom error formatters or registries).
