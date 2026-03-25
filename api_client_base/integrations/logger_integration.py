"""Optional integration with Logger_Package for structured API logging."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from ..request.models import APIRequest, APIResponse

# Attempt to import logger_pkg — graceful degradation if not installed
try:
    from logger_pkg import get_logger, bind_context, reset_context, new_correlation_id

    _HAS_LOGGER_PKG = True
except ImportError:
    _HAS_LOGGER_PKG = False


def is_available() -> bool:
    """Check if Logger_Package is installed and importable."""
    return _HAS_LOGGER_PKG


def get_api_logger(name: str = "api_client_base") -> logging.Logger:
    """Get a logger instance.

    Uses Logger_Package's ``get_logger`` if available, otherwise
    falls back to the standard library.

    Args:
        name: Logger name.

    Returns:
        Logger instance.
    """
    if _HAS_LOGGER_PKG:
        return get_logger(name)
    return logging.getLogger(name)


def bind_request_context(
    request: APIRequest,
    *,
    client_name: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> Any:
    """Bind per-request context fields for structured logging.

    Uses Logger_Package's ``bind_context()`` if available. The bound
    context propagates to all log messages until reset.

    Args:
        request: The outgoing API request.
        client_name: Name of the concrete client class.
        endpoint: Endpoint name from the registry.

    Returns:
        Context token for later reset, or None if Logger_Package is unavailable.
    """
    if not _HAS_LOGGER_PKG:
        return None

    fields: Dict[str, Any] = {
        "correlation_id": request.metadata.get(
            "correlation_id", new_correlation_id()
        ),
        "http_method": request.method,
        "url": request.url,
    }
    if client_name:
        fields["api_client"] = client_name
    if endpoint:
        fields["endpoint"] = endpoint
    if "attempt" in request.metadata:
        fields["attempt"] = request.metadata["attempt"]

    return bind_context(**fields)


def unbind_request_context(token: Any) -> None:
    """Reset the request context using the token from ``bind_request_context``.

    Args:
        token: Token returned by ``bind_request_context``.
    """
    if _HAS_LOGGER_PKG and token is not None:
        reset_context(token)


def log_request(
    logger: logging.Logger,
    request: APIRequest,
    *,
    log_body: bool = False,
) -> None:
    """Log an outgoing API request at INFO level.

    Args:
        logger: Logger instance.
        request: The outgoing request.
        log_body: If True, log the request body at DEBUG level.
    """
    logger.info(
        "API request: %s %s",
        request.method,
        request.url,
        extra={"params": request.params} if request.params else {},
    )
    if log_body and request.body is not None:
        logger.debug("Request body: %s", _truncate(str(request.body)))


def log_response(
    logger: logging.Logger,
    response: APIResponse,
    *,
    log_body: bool = False,
) -> None:
    """Log an API response at INFO (success) or WARNING (error) level.

    Args:
        logger: Logger instance.
        response: The received response.
        log_body: If True, log the response body at DEBUG level.
    """
    level = logging.INFO if response.is_success else logging.WARNING
    logger.log(
        level,
        "API response: %s %s → %d (%.1fms)",
        response.request.method if response.request else "?",
        response.request.url if response.request else "?",
        response.status_code,
        response.elapsed_ms,
    )
    if log_body and response.body is not None:
        logger.debug("Response body: %s", _truncate(str(response.body)))


def log_error(
    logger: logging.Logger,
    error: Exception,
    request: Optional[APIRequest] = None,
) -> None:
    """Log an API error at ERROR level.

    Args:
        logger: Logger instance.
        error: The exception that occurred.
        request: The request that caused the error, if available.
    """
    if request:
        logger.error(
            "API error: %s %s → %s: %s",
            request.method,
            request.url,
            type(error).__name__,
            error,
        )
    else:
        logger.error("API error: %s: %s", type(error).__name__, error)


def log_retry(
    logger: logging.Logger,
    attempt: int,
    max_retries: int,
    delay: float,
    reason: str = "",
) -> None:
    """Log a retry attempt at WARNING level.

    Args:
        logger: Logger instance.
        attempt: Current attempt number.
        max_retries: Maximum retry count.
        delay: Delay before next attempt in seconds.
        reason: Reason for the retry.
    """
    logger.warning(
        "Retrying request (attempt %d/%d, delay=%.1fs)%s",
        attempt,
        max_retries,
        delay,
        f": {reason}" if reason else "",
    )


def _truncate(text: str, max_length: int = 1000) -> str:
    """Truncate text for log output."""
    if len(text) <= max_length:
        return text
    return text[:max_length] + f"... (truncated, {len(text)} total)"
