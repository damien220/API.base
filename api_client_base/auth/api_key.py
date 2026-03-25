"""API Key authentication strategy."""

from __future__ import annotations

import threading
from typing import Optional

from .base import AbstractAuthStrategy
from ..request.models import APIRequest
from ..types import AuthLocation


class APIKeyAuth(AbstractAuthStrategy):
    """Authenticates requests using an API key.

    Supports injecting the key as:
    - A header (default): e.g., ``Authorization: Bearer sk-...`` or ``X-API-Key: sk-...``
    - A query parameter: e.g., ``?api_key=sk-...``

    Args:
        api_key: The API key string.
        location: Where to place the key (header or query).
        header_name: Header name when location is HEADER. Defaults to "Authorization".
        prefix: Prefix before the key in the header value (e.g., "Bearer"). None for no prefix.
        param_name: Query parameter name when location is QUERY. Defaults to "api_key".
    """

    def __init__(
        self,
        api_key: str,
        *,
        location: AuthLocation = AuthLocation.HEADER,
        header_name: str = "Authorization",
        prefix: Optional[str] = "Bearer",
        param_name: str = "api_key",
    ) -> None:
        self._api_key = api_key
        self._location = location
        self._header_name = header_name
        self._prefix = prefix
        self._param_name = param_name
        self._lock = threading.Lock()

    async def authenticate(self, request: APIRequest) -> APIRequest:
        """Inject the API key into the request."""
        if self._location == AuthLocation.HEADER:
            value = f"{self._prefix} {self._api_key}" if self._prefix else self._api_key
            request.headers[self._header_name] = value
        elif self._location == AuthLocation.QUERY:
            request.params[self._param_name] = self._api_key
        return request

    def rotate_key(self, new_key: str) -> None:
        """Swap the API key without downtime (thread-safe)."""
        with self._lock:
            self._api_key = new_key

    @property
    def redacted_key(self) -> str:
        """Return a redacted version of the key for logging."""
        if len(self._api_key) <= 8:
            return "***"
        return f"{self._api_key[:4]}...{self._api_key[-4:]}"
