"""Fluent RequestBuilder for constructing APIRequest objects."""

from __future__ import annotations

from typing import Any, Dict, Optional
from urllib.parse import urlencode, urljoin

from .models import APIRequest
from ..types import HttpMethod, ContentType


class RequestBuilder:
    """Fluent builder for constructing API requests.

    Usage::

        request = (
            RequestBuilder()
            .method("POST")
            .path("/v1/chat/completions")
            .header("X-Custom", "value")
            .json_body({"model": "gpt-4", "messages": [...]})
            .timeout(30.0)
            .build()
        )
    """

    def __init__(self) -> None:
        self._method: str = HttpMethod.GET.value
        self._base_url: str = ""
        self._path: str = ""
        self._headers: Dict[str, str] = {}
        self._params: Dict[str, Any] = {}
        self._body: Any = None
        self._files: Optional[Dict[str, Any]] = None
        self._timeout: Optional[float] = None
        self._metadata: Dict[str, Any] = {}
        self._content_type: Optional[str] = None

    def method(self, method: str) -> RequestBuilder:
        """Set the HTTP method."""
        self._method = method.upper()
        return self

    def base_url(self, url: str) -> RequestBuilder:
        """Set the base URL."""
        self._base_url = url.rstrip("/")
        return self

    def path(self, path: str) -> RequestBuilder:
        """Set the request path."""
        self._path = path if path.startswith("/") else f"/{path}"
        return self

    def header(self, key: str, value: str) -> RequestBuilder:
        """Add a single header."""
        self._headers[key] = value
        return self

    def headers(self, headers: Dict[str, str]) -> RequestBuilder:
        """Add multiple headers."""
        self._headers.update(headers)
        return self

    def param(self, key: str, value: Any) -> RequestBuilder:
        """Add a single query parameter."""
        self._params[key] = value
        return self

    def params(self, params: Dict[str, Any]) -> RequestBuilder:
        """Add multiple query parameters."""
        self._params.update(params)
        return self

    def json_body(self, data: Any) -> RequestBuilder:
        """Set a JSON body."""
        self._body = data
        self._content_type = ContentType.JSON.value
        return self

    def form_body(self, data: Dict[str, Any]) -> RequestBuilder:
        """Set a form-encoded body."""
        self._body = data
        self._content_type = ContentType.FORM.value
        return self

    def raw_body(self, data: Any, content_type: str = ContentType.OCTET_STREAM.value) -> RequestBuilder:
        """Set a raw body with explicit content type."""
        self._body = data
        self._content_type = content_type
        return self

    def file(self, field_name: str, file_data: Any) -> RequestBuilder:
        """Add a file for multipart upload.

        Args:
            field_name: The form field name.
            file_data: A tuple of (filename, file_obj) or (filename, file_obj, content_type).
        """
        if self._files is None:
            self._files = {}
        self._files[field_name] = file_data
        return self

    def timeout(self, seconds: float) -> RequestBuilder:
        """Set the request timeout."""
        self._timeout = seconds
        return self

    def meta(self, key: str, value: Any) -> RequestBuilder:
        """Attach metadata to the request."""
        self._metadata[key] = value
        return self

    def build(self) -> APIRequest:
        """Build and return the APIRequest."""
        url = self._base_url + self._path

        headers = dict(self._headers)
        if self._content_type and self._files is None:
            headers.setdefault("Content-Type", self._content_type)

        return APIRequest(
            method=self._method,
            url=url,
            headers=headers,
            params=dict(self._params),
            body=self._body,
            files=self._files,
            timeout=self._timeout,
            metadata=dict(self._metadata),
        )
