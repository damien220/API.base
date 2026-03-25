"""SyncAPIClient — synchronous wrapper using httpx.Client."""

from __future__ import annotations

from typing import Any, Dict, Iterator, Optional

import httpx

from .abstract_client import AbstractAPIClient
from ..config.client_config import APIClientConfig
from ..exceptions.api_exceptions import (
    APIConnectionError,
    APITimeoutError,
    ResponseParsingError,
)
from ..request.models import APIRequest, APIResponse


class SyncAPIClient(AbstractAPIClient):
    """Synchronous API client backed by httpx.Client.

    Wraps the async abstract interface so that callers in synchronous
    codebases can use the same API without an event loop::

        with MySyncClient(config) as client:
            response = client.get_sync("/users")

    Internally delegates lifecycle hooks (pre_request, post_response,
    on_error) through a private event loop.
    """

    def __init__(self, config: APIClientConfig) -> None:
        super().__init__(config)
        self._http_client: Optional[httpx.Client] = None

    # ------------------------------------------------------------------
    # Sync public interface
    # ------------------------------------------------------------------

    def request_sync(
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
        """Synchronous request dispatcher."""
        import asyncio

        return asyncio.get_event_loop().run_until_complete(
            self.request(
                method,
                path,
                headers=headers,
                params=params,
                json=json,
                data=data,
                files=files,
                timeout=timeout,
                metadata=metadata,
            )
        )

    def get_sync(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request_sync("GET", path, **kwargs)

    def post_sync(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request_sync("POST", path, **kwargs)

    def put_sync(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request_sync("PUT", path, **kwargs)

    def patch_sync(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request_sync("PATCH", path, **kwargs)

    def delete_sync(self, path: str, **kwargs: Any) -> APIResponse:
        return self.request_sync("DELETE", path, **kwargs)

    # ------------------------------------------------------------------
    # Sync connection lifecycle
    # ------------------------------------------------------------------

    def connect_sync(self) -> None:
        """Initialize the httpx.Client."""
        if self._http_client is not None:
            return
        self._http_client = httpx.Client(
            timeout=httpx.Timeout(
                self._config.timeout,
                connect=self._config.connect_timeout,
            ),
            verify=self._config.verify_ssl,
            proxy=self._config.proxy,
            follow_redirects=self._config.follow_redirects,
        )

    def disconnect_sync(self) -> None:
        """Close the httpx.Client."""
        if self._http_client is not None:
            self._http_client.close()
            self._http_client = None

    def __enter__(self) -> SyncAPIClient:
        self.connect_sync()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.disconnect_sync()

    # ------------------------------------------------------------------
    # Streaming (sync)
    # ------------------------------------------------------------------

    def stream_sync(
        self,
        method: str,
        path: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json: Any = None,
        data: Any = None,
        timeout: Optional[float] = None,
    ) -> Iterator[bytes]:
        """Stream a response body synchronously."""
        self._ensure_sync_client()
        client = self._http_client
        assert client is not None

        url = self._build_url(path)
        merged_headers = {**self._default_headers, **(headers or {})}

        kwargs: Dict[str, Any] = {
            "method": method.upper(),
            "url": url,
            "headers": merged_headers,
            "params": params or None,
            "timeout": timeout or self._config.timeout,
        }
        if json is not None:
            kwargs["json"] = json
        elif data is not None:
            kwargs["content"] = data

        try:
            with client.stream(**kwargs) as response:
                yield from response.iter_bytes()
        except httpx.TimeoutException as exc:
            raise APITimeoutError(f"Stream timed out: {method} {url}") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(f"Stream error: {exc}") from exc

    # ------------------------------------------------------------------
    # Abstract method implementations (async wrappers over sync transport)
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        self.connect_sync()

    async def disconnect(self) -> None:
        self.disconnect_sync()

    async def _send_request(self, request: APIRequest) -> httpx.Response:
        """Send the request via the sync httpx.Client."""
        self._ensure_sync_client()
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
            return client.request(**kwargs)
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
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_sync_client(self) -> None:
        if self._http_client is None:
            self.connect_sync()

    @staticmethod
    def _parse_body(response: httpx.Response) -> Any:
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
        return response.content
