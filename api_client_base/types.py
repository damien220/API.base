"""Shared type definitions and enums for api_client_base."""

from enum import Enum
from typing import Any, Callable, Awaitable, Dict, List, Optional, Union


class HttpMethod(str, Enum):
    """HTTP request methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    PATCH = "PATCH"
    DELETE = "DELETE"
    HEAD = "HEAD"
    OPTIONS = "OPTIONS"


class ContentType(str, Enum):
    """Common content types for API requests."""

    JSON = "application/json"
    FORM = "application/x-www-form-urlencoded"
    MULTIPART = "multipart/form-data"
    XML = "application/xml"
    TEXT = "text/plain"
    OCTET_STREAM = "application/octet-stream"


class AuthLocation(str, Enum):
    """Where authentication credentials are placed in the request."""

    HEADER = "header"
    QUERY = "query"
    BODY = "body"


class RetryBackoff(str, Enum):
    """Backoff strategies for retry policies."""

    FIXED = "fixed"
    EXPONENTIAL = "exponential"
    EXPONENTIAL_JITTER = "exponential_jitter"


# Status codes that are safe to retry
RETRIABLE_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})

# Type aliases
Headers = Dict[str, str]
QueryParams = Dict[str, Union[str, int, float, bool, List[str]]]
JsonBody = Union[Dict[str, Any], List[Any], str, int, float, bool, None]
RequestHook = Callable[..., Awaitable[Any]]
