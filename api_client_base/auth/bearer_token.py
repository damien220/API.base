"""Bearer token authentication strategy with optional refresh support."""

from __future__ import annotations

import threading
import time
from typing import Any, Awaitable, Callable, Optional

from .base import AbstractAuthStrategy
from ..request.models import APIRequest


# Type for an async callable that returns (new_token, expires_at_epoch)
TokenRefreshCallback = Callable[[], Awaitable[tuple[str, Optional[float]]]]


class BearerTokenAuth(AbstractAuthStrategy):
    """Authenticates requests with a Bearer token.

    Supports both static tokens and tokens that can be refreshed via
    an async callback before they expire.

    Args:
        token: The initial bearer token.
        expires_at: Unix timestamp when the token expires. None = never expires.
        refresh_callback: Async callable that returns (new_token, new_expires_at).
        refresh_buffer: Seconds before expiry to trigger a proactive refresh.
    """

    def __init__(
        self,
        token: str,
        *,
        expires_at: Optional[float] = None,
        refresh_callback: Optional[TokenRefreshCallback] = None,
        refresh_buffer: float = 30.0,
    ) -> None:
        self._token = token
        self._expires_at = expires_at
        self._refresh_callback = refresh_callback
        self._refresh_buffer = refresh_buffer
        self._lock = threading.Lock()

    async def authenticate(self, request: APIRequest) -> APIRequest:
        """Inject Bearer token into the Authorization header.

        Automatically refreshes the token if it is expired or about to expire.
        """
        if self.is_expired() and self._refresh_callback is not None:
            await self.refresh()
        request.headers["Authorization"] = f"Bearer {self._token}"
        return request

    async def refresh(self) -> None:
        """Refresh the token using the registered callback."""
        if self._refresh_callback is None:
            return
        new_token, new_expires_at = await self._refresh_callback()
        with self._lock:
            self._token = new_token
            self._expires_at = new_expires_at

    def is_expired(self) -> bool:
        """Check if the token has expired or is about to expire."""
        if self._expires_at is None:
            return False
        return time.time() >= (self._expires_at - self._refresh_buffer)

    def set_token(self, token: str, expires_at: Optional[float] = None) -> None:
        """Manually set a new token (thread-safe)."""
        with self._lock:
            self._token = token
            self._expires_at = expires_at

    @property
    def redacted_token(self) -> str:
        """Return a redacted version of the token for logging."""
        if len(self._token) <= 8:
            return "***"
        return f"{self._token[:4]}...{self._token[-4:]}"
