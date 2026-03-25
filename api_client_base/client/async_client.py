"""AsyncAPIClient — full async implementation using httpx.AsyncClient."""

from __future__ import annotations

import time
from typing import Any, AsyncIterator, Dict, Optional

import httpx

from .abstract_client import AbstractAPIClient
from ..config.client_config import APIClientConfig
from ..exceptions.api_exceptions import (
    APIConnectionError,
    APITimeoutError,
    ResponseParsingError,
)
from ..request.models import APIRequest, APIResponse


class AsyncAPIClient(AbstractAPIClient):
    """Async API client backed by httpx.AsyncClient.

    This is the primary implementation. Use it in async codebases::

        async with MyClient(config) as client:
            response = await client.get("/users")
    """

    def __init__(self, config: APIClientConfig) -> None:
        super().__init__(config)
        self._http_client: Optional[httpx.AsyncClient] = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        """Initialize the httpx.AsyncClient."""
        if self._http_client is not None:
            return
        self._http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                self._config.timeout,
                connect=self._config.connect_timeout,
            ),
            verify=self._config.verify_ssl,
            proxy=self._config.proxy,
            follow_redirects=self._config.follow_redirects,
        )

    async def disconnect(self) -> None:
        """Close the httpx.AsyncClient and release connections."""
        if self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def health_check(self) -> bool:
        """Verify connectivity by sending a HEAD request to the base URL."""
        try:
            await self._ensure_client()
            resp = await self._http_client.head(  # type: ignore[union-attr]
                self._base_url,
                timeout=self._config.connect_timeout,
            )
            return resp.status_code < 500
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Transport implementation
    # ------------------------------------------------------------------

    async def _send_request(self, request: APIRequest) -> httpx.Response:
        """Send the request via httpx and return the raw Response."""
        await self._ensure_client()
        client = self._http_client
        assert client is not None

        kwargs: Dict[str, Any] = {
            "method": request.method,
            "url": request.url,
            "headers": request.headers,
            "params": request.params or None,
            "timeout": request.timeout,
        }

        body_type = request.metadata.get("body_type")
        if request.files:
            kwargs["files"] = request.files
            if isinstance(request.body, dict):
                kwargs["data"] = request.body
        elif body_type == "json" and request.body is not None:
            kwargs["json"] = request.body
        elif request.body is not None:
            kwargs["content"] = request.body

        try:
            return await client.request(**kwargs)
        except httpx.TimeoutException as exc:
            raise APITimeoutError(
                f"Request timed out: {request.method} {request.url}",
                request=request,
            ) from exc
        except httpx.ConnectError as exc:
            raise APIConnectionError(
                f"Connection failed: {request.method} {request.url}",
                request=request,
            ) from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(
                f"HTTP error: {exc}",
                request=request,
            ) from exc

    async def _parse_response(
        self, raw_response: httpx.Response, request: APIRequest
    ) -> APIResponse:
        """Parse httpx.Response into an APIResponse."""
        elapsed_ms = raw_response.elapsed.total_seconds() * 1000

        headers = dict(raw_response.headers)

        # Parse body based on content type
        body = self._parse_body(raw_response)

        return APIResponse(
            status_code=raw_response.status_code,
            headers=headers,
            body=body,
            raw_response=raw_response,
            elapsed_ms=elapsed_ms,
            request=request,
        )

    # ------------------------------------------------------------------
    # Streaming support
    # ------------------------------------------------------------------

    async def stream(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        timeout: Optional[float] = None,
    ) -> AsyncIterator[bytes]:
        """Stream a response body in chunks.

        Yields raw bytes chunks as they arrive. Useful for
        SSE (Server-Sent Events) or large file downloads.
        """
        await self._ensure_client()
        client = self._http_client
        assert client is not None

        url = self._build_url(path)
        merged_headers = {**self._default_headers, **(headers or {})}

        # Authenticate
        api_request = APIRequest(
            method=method.upper(),
            url=url,
            headers=merged_headers,
            params=params or {},
            body=json if json is not None else data,
            timeout=timeout or self._config.timeout,
        )
        if json is not None:
            api_request.metadata["body_type"] = "json"

        if self._auth is not None:
            if self._auth.is_expired():
                await self._auth.refresh()
            api_request = await self._auth.authenticate(api_request)

        kwargs: Dict[str, Any] = {
            "method": api_request.method,
            "url": api_request.url,
            "headers": api_request.headers,
            "params": api_request.params or None,
            "timeout": api_request.timeout,
        }
        if json is not None:
            kwargs["json"] = json
        elif data is not None:
            kwargs["content"] = data

        try:
            async with client.stream(**kwargs) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk
        except httpx.TimeoutException as exc:
            raise APITimeoutError(
                f"Stream timed out: {method} {url}",
                request=api_request,
            ) from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(
                f"Stream error: {exc}",
                request=api_request,
            ) from exc

    # ------------------------------------------------------------------
    # Parsed stream helpers
    # ------------------------------------------------------------------

    async def stream_sse(
        self,
        method: str,
        path: str,
        *,
        parse_json: bool = True,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Stream Server-Sent Events from an API endpoint.

        Yields ``SSEEvent`` objects with parsed data. Stops at ``[DONE]``.

        Usage::

            async for event in client.stream_sse("POST", "/chat/completions", json=body):
                if event.is_done:
                    break
                print(event.data)

        Args:
            method: HTTP method.
            path: URL path.
            parse_json: Auto-parse event data as JSON.
            **kwargs: Passed to ``stream()``.

        Yields:
            SSEEvent instances.
        """
        from ..response.stream_parsers import parse_sse

        raw_stream = self.stream(method, path, **kwargs)
        async for event in parse_sse(raw_stream, parse_json=parse_json):
            yield event

    async def stream_ndjson(
        self,
        method: str,
        path: str,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        """Stream Newline-Delimited JSON from an API endpoint.

        Yields parsed JSON objects, one per line.

        Args:
            method: HTTP method.
            path: URL path.
            **kwargs: Passed to ``stream()``.

        Yields:
            Parsed JSON objects.
        """
        from ..response.stream_parsers import parse_ndjson

        raw_stream = self.stream(method, path, **kwargs)
        async for obj in parse_ndjson(raw_stream):
            yield obj

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _ensure_client(self) -> None:
        """Lazily create the HTTP client if not yet connected."""
        if self._http_client is None:
            await self.connect()

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
        """Parse response body based on content type."""
        content_type = response.headers.get("content-type", "")

        if "application/json" in content_type:
            try:
                return response.json()
            except Exception:
                raise ResponseParsingError(
                    f"Failed to parse JSON response (status {response.status_code})"
                )

        if content_type.startswith("text/"):
            return response.text

        # Binary / unknown content type
        return response.content
