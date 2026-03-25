"""AbstractAPIClient — core base class for all API clients."""

from __future__ import annotations

import time
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, Optional

from ..auth.base import AbstractAuthStrategy
from ..config.client_config import APIClientConfig
from ..exceptions.api_exceptions import (
    APIClientError,
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    AuthorizationError,
    CircuitOpenError,
    NotFoundError,
    RateLimitError,
    ResponseParsingError,
    ServerError,
    ValidationError,
)
from ..pagination.paginator import Paginator
from ..pagination.strategies import PaginationStrategy
from ..request.models import APIRequest, APIResponse
from ..request.middleware import MiddlewareChain
from ..resilience.retry import RetryPolicy
from ..resilience.rate_limiter import RateLimiter
from ..resilience.circuit_breaker import CircuitBreaker
from ..resilience.timeout import TimeoutPolicy
from ..routing.registry import EndpointRegistry
from ..types import HttpMethod


class AbstractAPIClient(ABC):
    """Base class all API clients extend.

    Manages the full request lifecycle::

        configure → authenticate → build request → send → handle response/error

    Subclasses must implement ``_send_request`` and ``_parse_response``
    for the actual HTTP transport. Use ``AsyncAPIClient`` or ``SyncAPIClient``
    as the concrete base instead of subclassing this directly.
    """

    def __init__(self, config: APIClientConfig) -> None:
        self._config = config
        self._base_url = config.base_url.rstrip("/")
        if config.api_version:
            self._base_url = f"{self._base_url}/{config.api_version}"
        self._auth: Optional[AbstractAuthStrategy] = config.auth_strategy
        self._default_headers = {
            "User-Agent": config.user_agent,
            **config.default_headers,
        }

        # Routing
        self._endpoints = EndpointRegistry()

        # Middleware
        self._middleware = MiddlewareChain()

        # Resilience — initialized from config or defaults
        self._retry_policy = RetryPolicy(
            max_retries=config.max_retries,
            backoff=config.retry_backoff,
            base_delay=config.retry_base_delay,
            max_delay=config.retry_max_delay,
        )

        self._timeout_policy = TimeoutPolicy(
            default_timeout=config.timeout,
            default_connect_timeout=config.connect_timeout,
        )

        self._rate_limiter: Optional[RateLimiter] = None
        if config.rate_limit is not None:
            self._rate_limiter = RateLimiter(
                max_requests=config.rate_limit.max_requests,
                period=config.rate_limit.period_seconds,
                per_endpoint=config.rate_limit.per_endpoint,
            )

        self._circuit_breaker: Optional[CircuitBreaker] = None
        if config.circuit_breaker is not None:
            self._circuit_breaker = CircuitBreaker(
                failure_threshold=config.circuit_breaker.failure_threshold,
                recovery_timeout=config.circuit_breaker.recovery_timeout,
                success_threshold=config.circuit_breaker.success_threshold,
                per_endpoint=config.circuit_breaker.per_endpoint,
            )

    # ------------------------------------------------------------------
    # Public request interface
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        files: Optional[Dict[str, Any]] = None,
        timeout: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> APIResponse:
        """Core request dispatcher — orchestrates the full lifecycle.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: URL path relative to base_url (e.g., "/chat/completions").
            headers: Additional headers for this request.
            params: Query parameters.
            json: JSON-serializable body.
            data: Form-encoded or raw body.
            files: Multipart file uploads.
            timeout: Per-request timeout override.
            metadata: Arbitrary metadata attached to the request.

        Returns:
            Parsed APIResponse.

        Raises:
            APIClientError: On any API or transport error.
        """
        # Build the request object
        url = self._build_url(path)
        merged_headers = {**self._default_headers, **(headers or {})}

        body = json if json is not None else data

        api_request = APIRequest(
            method=method.upper(),
            url=url,
            headers=merged_headers,
            params=params or {},
            body=body,
            files=files,
            timeout=timeout or self._config.timeout,
            metadata={
                "correlation_id": str(uuid.uuid4()),
                "timestamp": time.time(),
                **(metadata or {}),
            },
        )

        # Mark if body is JSON for downstream serialization
        if json is not None:
            api_request.metadata["body_type"] = "json"
        elif data is not None:
            api_request.metadata["body_type"] = "data"

        # Resolve endpoint name for per-endpoint resilience
        endpoint_name: Optional[str] = metadata.get("endpoint") if metadata else None

        # Resolve timeout via policy
        api_request.timeout = self._timeout_policy.resolve_timeout(
            request_timeout=timeout,
            endpoint=endpoint_name,
        )

        # Circuit breaker check — fail fast if circuit is open
        if self._circuit_breaker is not None:
            self._circuit_breaker.check(endpoint_name)

        # Rate limiter — wait for token
        if self._rate_limiter is not None:
            await self._rate_limiter.acquire(endpoint_name)

        # Authenticate
        if self._auth is not None:
            if self._auth.is_expired():
                await self._auth.refresh()
            api_request = await self._auth.authenticate(api_request)

        # Pre-request hook
        api_request = await self.pre_request(api_request)

        # Middleware chain — before_request
        api_request = await self._middleware.process_request(api_request)

        # Send with retry
        last_error: Optional[Exception] = None
        max_attempts = self._retry_policy.max_retries + 1

        for attempt in range(1, max_attempts + 1):
            api_request.metadata["attempt"] = attempt
            try:
                raw_response = await self._send_request(api_request)
                api_response = await self._parse_response(raw_response, api_request)

                # Update rate limiter from response headers
                if self._rate_limiter is not None:
                    self._rate_limiter.update_from_headers(
                        api_response.headers, endpoint_name
                    )

                # Map HTTP error status codes to exceptions
                if not api_response.is_success:
                    error = self._map_status_to_error(api_response, api_request)

                    # Record failure for circuit breaker
                    if self._circuit_breaker is not None:
                        self._circuit_breaker.record_failure(endpoint_name)

                    retry_after = None
                    if isinstance(error, RateLimitError):
                        retry_after = error.retry_after

                    if (
                        error.retry_eligible
                        and self._retry_policy.should_retry(
                            attempt,
                            status_code=api_response.status_code,
                        )
                    ):
                        last_error = error
                        await self._retry_policy.wait(attempt, retry_after)
                        continue

                    await self.on_error(error, api_request)
                    raise error

                # Success — record for circuit breaker
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_success(endpoint_name)

                # Middleware chain — after_response
                api_response = await self._middleware.process_response(
                    api_response, api_request
                )

                # Post-response hook
                api_response = await self.post_response(api_response)
                return api_response

            except (APIClientError, CircuitOpenError):
                raise
            except Exception as exc:
                # Record failure for circuit breaker
                if self._circuit_breaker is not None:
                    self._circuit_breaker.record_failure(endpoint_name)

                is_timeout = isinstance(exc, APITimeoutError)
                is_conn = isinstance(exc, APIConnectionError)

                if self._retry_policy.should_retry(
                    attempt,
                    is_connection_error=is_conn,
                    is_timeout=is_timeout,
                ):
                    last_error = exc
                    await self._retry_policy.wait(attempt)
                    continue

                wrapped = APIClientError(
                    f"Request failed: {exc}",
                    request=api_request,
                )
                await self.on_error(wrapped, api_request)
                raise wrapped from exc

        # Should not reach here, but just in case
        raise last_error  # type: ignore[misc]

    # ------------------------------------------------------------------
    # HTTP convenience methods
    # ------------------------------------------------------------------

    async def get(self, path: str, **kwargs: Any) -> APIResponse:
        """HTTP GET shortcut."""
        return await self.request(HttpMethod.GET, path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> APIResponse:
        """HTTP POST shortcut."""
        return await self.request(HttpMethod.POST, path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> APIResponse:
        """HTTP PUT shortcut."""
        return await self.request(HttpMethod.PUT, path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> APIResponse:
        """HTTP PATCH shortcut."""
        return await self.request(HttpMethod.PATCH, path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> APIResponse:
        """HTTP DELETE shortcut."""
        return await self.request(HttpMethod.DELETE, path, **kwargs)

    async def upload(
        self, path: str, files: Dict[str, Any], **kwargs: Any
    ) -> APIResponse:
        """Multipart file upload shortcut."""
        return await self.request(HttpMethod.POST, path, files=files, **kwargs)

    # ------------------------------------------------------------------
    # Response transformation
    # ------------------------------------------------------------------

    async def request_as(
        self,
        model: type,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> Any:
        """Make a request and deserialize the response body into a typed model.

        Uses ``map_response`` to convert the raw response dict into a
        dataclass instance (or list of dataclass instances).

        Usage::

            @dataclass
            class User:
                id: int
                name: str

            user = await client.request_as(User, "GET", "/users/1")

        Args:
            model: Target type (dataclass or list[dataclass]).
            method: HTTP method.
            path: URL path.
            **kwargs: Passed to ``request()``.

        Returns:
            Deserialized model instance.
        """
        from ..response.model_mapping import map_response

        response = await self.request(method, path, **kwargs)
        return map_response(response.body, model)

    async def get_as(self, model: type, path: str, **kwargs: Any) -> Any:
        """GET and deserialize into a typed model."""
        return await self.request_as(model, HttpMethod.GET, path, **kwargs)

    async def post_as(self, model: type, path: str, **kwargs: Any) -> Any:
        """POST and deserialize into a typed model."""
        return await self.request_as(model, HttpMethod.POST, path, **kwargs)

    # ------------------------------------------------------------------
    # Pagination
    # ------------------------------------------------------------------

    def paginate(
        self,
        method: str,
        path: str,
        strategy: PaginationStrategy,
        *,
        params: Optional[Dict[str, Any]] = None,
        max_pages: Optional[int] = None,
        max_items: Optional[int] = None,
        **request_kwargs: Any,
    ) -> Paginator:
        """Create a paginator that auto-fetches all pages from a paginated endpoint.

        Returns a ``Paginator`` — an async iterator that yields individual
        items across all pages, transparently fetching the next page as needed.

        Usage::

            async for user in client.paginate("GET", "/users", strategy=CursorPagination()):
                print(user["name"])

            # Or collect all at once
            all_users = await client.paginate("GET", "/users", strategy=OffsetPagination()).collect()

        Args:
            method: HTTP method.
            path: URL path.
            strategy: Pagination strategy to use.
            params: Initial query parameters for the first page.
            max_pages: Maximum pages to fetch. None = no limit.
            max_items: Maximum items to yield. None = no limit.
            **request_kwargs: Extra kwargs passed to ``request()`` on each page fetch.

        Returns:
            A Paginator async iterator.
        """
        initial_params = dict(params or {})

        async def fetch_page(**page_params: Any) -> APIResponse:
            # Handle URL override from LinkHeaderPagination
            override_url = page_params.pop("_override_url", None)
            merged_params = {**initial_params, **page_params}
            if override_url:
                return await self.request(
                    method, override_url, params={}, **request_kwargs
                )
            return await self.request(
                method, path, params=merged_params, **request_kwargs
            )

        return Paginator(
            fetch_page=fetch_page,
            strategy=strategy,
            initial_params=initial_params,
            max_pages=max_pages,
            max_items=max_items,
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks — override in subclasses
    # ------------------------------------------------------------------

    async def pre_request(self, request: APIRequest) -> APIRequest:
        """Hook: modify request before sending. Override to customize."""
        return request

    async def post_response(self, response: APIResponse) -> APIResponse:
        """Hook: transform response after receiving. Override to customize."""
        return response

    async def on_error(self, error: Exception, request: APIRequest) -> None:
        """Hook: react to errors. Override to add logging, alerting, etc."""

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Initialize the HTTP client / connection pool."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the HTTP client / connection pool."""

    async def health_check(self) -> bool:
        """Verify API reachability. Override with a real health endpoint."""
        return True

    async def __aenter__(self) -> AbstractAPIClient:
        await self.connect()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Abstract transport methods — implemented by Async/Sync clients
    # ------------------------------------------------------------------

    @abstractmethod
    async def _send_request(self, request: APIRequest) -> Any:
        """Send the HTTP request and return the raw transport response."""

    @abstractmethod
    async def _parse_response(
        self, raw_response: Any, request: APIRequest
    ) -> APIResponse:
        """Parse the raw transport response into an APIResponse."""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_url(self, path: str) -> str:
        """Combine base URL with the request path."""
        if path.startswith(("http://", "https://")):
            return path
        separator = "" if path.startswith("/") else "/"
        return f"{self._base_url}{separator}{path}"

    def _map_status_to_error(
        self, response: APIResponse, request: APIRequest
    ) -> APIClientError:
        """Map an HTTP error status code to the appropriate exception."""
        status = response.status_code
        # Try to extract error message from response body
        message = self._extract_error_message(response)

        common = dict(request=request, response=response)

        if status == 401:
            return AuthenticationError(message, **common)
        if status == 403:
            return AuthorizationError(message, **common)
        if status == 404:
            return NotFoundError(message, **common)
        if status in (400, 422):
            return ValidationError(message, **common)
        if status == 429:
            retry_after = self._parse_retry_after(response)
            return RateLimitError(
                message,
                retry_after=retry_after,
                **common,
            )
        if 500 <= status < 600:
            return ServerError(message, status_code=status, **common)

        return APIClientError(
            message, status_code=status, retry_eligible=False, **common
        )

    @staticmethod
    def _extract_error_message(response: APIResponse) -> str:
        """Best-effort extraction of error message from response body."""
        body = response.body
        if isinstance(body, dict):
            for key in ("message", "error", "detail", "error_description"):
                if key in body:
                    val = body[key]
                    if isinstance(val, dict) and "message" in val:
                        return str(val["message"])
                    return str(val)
        if isinstance(body, str) and body:
            return body[:200]
        return f"HTTP {response.status_code}"

    @staticmethod
    def _parse_retry_after(response: APIResponse) -> Optional[float]:
        """Parse Retry-After header value."""
        value = response.headers.get("Retry-After") or response.headers.get(
            "retry-after"
        )
        if value is None:
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def config(self) -> APIClientConfig:
        """Access the client configuration."""
        return self._config

    @property
    def base_url(self) -> str:
        """The resolved base URL (including API version if set)."""
        return self._base_url

    @property
    def endpoints(self) -> EndpointRegistry:
        """Access the endpoint registry."""
        return self._endpoints

    @property
    def middleware(self) -> MiddlewareChain:
        """Access the middleware chain."""
        return self._middleware

    @property
    def retry_policy(self) -> RetryPolicy:
        """Access the retry policy."""
        return self._retry_policy

    @property
    def timeout_policy(self) -> TimeoutPolicy:
        """Access the timeout policy."""
        return self._timeout_policy

    @property
    def rate_limiter(self) -> Optional[RateLimiter]:
        """Access the rate limiter (None if not configured)."""
        return self._rate_limiter

    @property
    def circuit_breaker(self) -> Optional[CircuitBreaker]:
        """Access the circuit breaker (None if not configured)."""
        return self._circuit_breaker
