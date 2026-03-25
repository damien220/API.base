"""Request middleware chain for pre/post request processing."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, List, Optional
import uuid
import time

from .models import APIRequest, APIResponse


class RequestMiddleware(ABC):
    """Base class for request middleware.

    Middleware intercepts the request lifecycle at two points:
    - ``before_request``: called before the request is sent
    - ``after_response``: called after a response is received

    Middleware is executed in order for ``before_request`` and in
    reverse order for ``after_response`` (onion model).
    """

    @abstractmethod
    async def before_request(self, request: APIRequest) -> APIRequest:
        """Process the request before it is sent.

        Args:
            request: The outgoing request.

        Returns:
            The (possibly modified) request.
        """

    @abstractmethod
    async def after_response(
        self, response: APIResponse, request: APIRequest
    ) -> APIResponse:
        """Process the response after it is received.

        Args:
            response: The received response.
            request: The original request.

        Returns:
            The (possibly modified) response.
        """


# Type for the "next" handler that middleware calls to proceed
NextHandler = Callable[[APIRequest], Awaitable[APIResponse]]


class MiddlewareChain:
    """Manages an ordered list of middleware and executes them.

    Middleware is applied in onion order:
    - ``before_request``: first added → first executed
    - ``after_response``: first added → last executed

    Usage::

        chain = MiddlewareChain()
        chain.add(LoggingMiddleware())
        chain.add(MetricsMiddleware())

        request = await chain.process_request(request)
        # ... send request ...
        response = await chain.process_response(response, request)
    """

    def __init__(self) -> None:
        self._middleware: List[RequestMiddleware] = []

    def add(self, middleware: RequestMiddleware) -> None:
        """Append middleware to the chain."""
        self._middleware.append(middleware)

    def insert(self, index: int, middleware: RequestMiddleware) -> None:
        """Insert middleware at a specific position."""
        self._middleware.insert(index, middleware)

    def remove(self, middleware: RequestMiddleware) -> None:
        """Remove a middleware instance from the chain."""
        self._middleware.remove(middleware)

    def clear(self) -> None:
        """Remove all middleware."""
        self._middleware.clear()

    async def process_request(self, request: APIRequest) -> APIRequest:
        """Run all middleware ``before_request`` hooks in order."""
        for mw in self._middleware:
            request = await mw.before_request(request)
        return request

    async def process_response(
        self, response: APIResponse, request: APIRequest
    ) -> APIResponse:
        """Run all middleware ``after_response`` hooks in reverse order."""
        for mw in reversed(self._middleware):
            response = await mw.after_response(response, request)
        return response

    @property
    def middleware_list(self) -> List[RequestMiddleware]:
        """Return the current middleware list (read-only copy)."""
        return list(self._middleware)

    def __len__(self) -> int:
        return len(self._middleware)


# ======================================================================
# Built-in middleware implementations
# ======================================================================


class IdempotencyMiddleware(RequestMiddleware):
    """Attaches an idempotency key to mutating requests.

    Adds an ``Idempotency-Key`` header to POST/PUT/PATCH requests
    that don't already have one, ensuring safe retries.

    Args:
        header_name: The idempotency header name. Defaults to "Idempotency-Key".
        methods: HTTP methods that should get idempotency keys.
    """

    def __init__(
        self,
        header_name: str = "Idempotency-Key",
        methods: Optional[set[str]] = None,
    ) -> None:
        self._header_name = header_name
        self._methods = methods or {"POST", "PUT", "PATCH"}

    async def before_request(self, request: APIRequest) -> APIRequest:
        if (
            request.method in self._methods
            and self._header_name not in request.headers
        ):
            request.headers[self._header_name] = str(uuid.uuid4())
        return request

    async def after_response(
        self, response: APIResponse, request: APIRequest
    ) -> APIResponse:
        return response


class TimingMiddleware(RequestMiddleware):
    """Records request timing in metadata.

    Adds ``timing_start`` and ``timing_end`` to request/response metadata
    for downstream metrics collection.
    """

    async def before_request(self, request: APIRequest) -> APIRequest:
        request.metadata["timing_start"] = time.monotonic()
        return request

    async def after_response(
        self, response: APIResponse, request: APIRequest
    ) -> APIResponse:
        start = request.metadata.get("timing_start")
        if start is not None:
            response.metadata["timing_elapsed_ms"] = (
                (time.monotonic() - start) * 1000
            )
        return response


class HeaderInjectionMiddleware(RequestMiddleware):
    """Injects static headers into every request.

    Args:
        headers: Dictionary of headers to inject.
        overwrite: If False, won't overwrite existing headers.
    """

    def __init__(
        self, headers: dict[str, str], *, overwrite: bool = False
    ) -> None:
        self._headers = headers
        self._overwrite = overwrite

    async def before_request(self, request: APIRequest) -> APIRequest:
        for key, value in self._headers.items():
            if self._overwrite or key not in request.headers:
                request.headers[key] = value
        return request

    async def after_response(
        self, response: APIResponse, request: APIRequest
    ) -> APIResponse:
        return response
