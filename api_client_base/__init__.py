"""API Client Base — abstract, reusable base for building external service API clients."""

__version__ = "0.1.0"

# Client classes
from .client.abstract_client import AbstractAPIClient
from .client.async_client import AsyncAPIClient
from .client.sync_client import SyncAPIClient

# Authentication strategies
from .auth.base import AbstractAuthStrategy
from .auth.api_key import APIKeyAuth
from .auth.bearer_token import BearerTokenAuth
from .auth.oauth2 import OAuth2Auth, OAuth2Flow
from .auth.custom import CustomAuth

# Request / Response models
from .request.models import APIRequest, APIResponse
from .request.builder import RequestBuilder
from .request.middleware import (
    RequestMiddleware,
    MiddlewareChain,
    IdempotencyMiddleware,
    TimingMiddleware,
    HeaderInjectionMiddleware,
)

# Routing
from .routing.endpoint import EndpointDefinition
from .routing.registry import EndpointRegistry
from .routing.url_builder import URLBuilder

# Pagination
from .pagination.strategies import (
    PaginationStrategy,
    PageInfo,
    CursorPagination,
    OffsetPagination,
    PageNumberPagination,
    LinkHeaderPagination,
)
from .pagination.paginator import Paginator

# Response transformation
from .response.model_mapping import map_response, map_response_list
from .response.stream_parsers import SSEEvent, parse_sse, parse_ndjson, parse_text_lines

# Resilience
from .resilience.retry import RetryPolicy
from .resilience.rate_limiter import RateLimiter
from .resilience.circuit_breaker import CircuitBreaker, CircuitState, CircuitStats
from .resilience.timeout import TimeoutPolicy

# Configuration
from .config.client_config import APIClientConfig, RateLimitConfig, CircuitBreakerConfig

# Exceptions
from .exceptions.api_exceptions import (
    APIClientError,
    AuthenticationError,
    AuthorizationError,
    NotFoundError,
    ValidationError,
    RateLimitError,
    ServerError,
    APITimeoutError,
    APIConnectionError,
    CircuitOpenError,
    ResponseParsingError,
)

# Types and enums
from .types import HttpMethod, ContentType, AuthLocation, RetryBackoff

__all__ = [
    # Version
    "__version__",
    # Clients
    "AbstractAPIClient",
    "AsyncAPIClient",
    "SyncAPIClient",
    # Auth
    "AbstractAuthStrategy",
    "APIKeyAuth",
    "BearerTokenAuth",
    "OAuth2Auth",
    "OAuth2Flow",
    "CustomAuth",
    # Request / Response
    "APIRequest",
    "APIResponse",
    "RequestBuilder",
    # Middleware
    "RequestMiddleware",
    "MiddlewareChain",
    "IdempotencyMiddleware",
    "TimingMiddleware",
    "HeaderInjectionMiddleware",
    # Routing
    "EndpointDefinition",
    "EndpointRegistry",
    "URLBuilder",
    # Resilience
    "RetryPolicy",
    "RateLimiter",
    "CircuitBreaker",
    "CircuitState",
    "CircuitStats",
    "TimeoutPolicy",
    # Config
    "APIClientConfig",
    "RateLimitConfig",
    "CircuitBreakerConfig",
    # Exceptions
    "APIClientError",
    "AuthenticationError",
    "AuthorizationError",
    "NotFoundError",
    "ValidationError",
    "RateLimitError",
    "ServerError",
    "APITimeoutError",
    "APIConnectionError",
    "CircuitOpenError",
    "ResponseParsingError",
    # Pagination
    "PaginationStrategy",
    "PageInfo",
    "CursorPagination",
    "OffsetPagination",
    "PageNumberPagination",
    "LinkHeaderPagination",
    "Paginator",
    # Response transformation
    "map_response",
    "map_response_list",
    "SSEEvent",
    "parse_sse",
    "parse_ndjson",
    "parse_text_lines",
    # Types
    "HttpMethod",
    "ContentType",
    "AuthLocation",
    "RetryBackoff",
]
