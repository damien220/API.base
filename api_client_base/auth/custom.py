"""Custom authentication strategy for user-defined auth schemes."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from .base import AbstractAuthStrategy
from ..request.models import APIRequest


# Type for the user-provided auth callable
AuthCallable = Callable[[APIRequest], Awaitable[APIRequest]]

# Type for the optional expiry check callable
ExpiryCallable = Callable[[], bool]

# Type for the optional refresh callable
RefreshCallable = Callable[[], Awaitable[None]]


class CustomAuth(AbstractAuthStrategy):
    """User-defined authentication strategy.

    Accepts a callable that receives an ``APIRequest`` and returns
    a modified request with credentials injected. This is the escape
    hatch for auth schemes not covered by the built-in strategies:
    HMAC signing, AWS SigV4, custom request signing, etc.

    Usage::

        async def hmac_signer(request: APIRequest) -> APIRequest:
            signature = hmac.new(secret, request.body, hashlib.sha256).hexdigest()
            request.headers["X-Signature"] = signature
            request.headers["X-Timestamp"] = str(int(time.time()))
            return request

        auth = CustomAuth(authenticate_fn=hmac_signer)

    For auth schemes that support token refresh::

        auth = CustomAuth(
            authenticate_fn=inject_token,
            is_expired_fn=lambda: token_expiry < time.time(),
            refresh_fn=fetch_new_token,
        )

    Args:
        authenticate_fn: Async callable that injects credentials into the request.
        is_expired_fn: Optional callable that returns True if credentials are expired.
        refresh_fn: Optional async callable that refreshes expired credentials.
        name: Optional name for this auth strategy (used in logging).
    """

    def __init__(
        self,
        authenticate_fn: AuthCallable,
        *,
        is_expired_fn: Optional[ExpiryCallable] = None,
        refresh_fn: Optional[RefreshCallable] = None,
        name: str = "custom",
    ) -> None:
        self._authenticate_fn = authenticate_fn
        self._is_expired_fn = is_expired_fn
        self._refresh_fn = refresh_fn
        self._name = name

    async def authenticate(self, request: APIRequest) -> APIRequest:
        """Delegate authentication to the user-provided callable."""
        return await self._authenticate_fn(request)

    async def refresh(self) -> None:
        """Delegate credential refresh to the user-provided callable."""
        if self._refresh_fn is not None:
            await self._refresh_fn()

    def is_expired(self) -> bool:
        """Delegate expiry check to the user-provided callable."""
        if self._is_expired_fn is not None:
            return self._is_expired_fn()
        return False

    @property
    def name(self) -> str:
        """The name of this custom auth strategy."""
        return self._name
