"""Abstract base class for authentication strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..request.models import APIRequest


class AbstractAuthStrategy(ABC):
    """Injects credentials into outgoing requests.

    Subclass this to implement a specific authentication scheme
    (API key, Bearer token, OAuth2, HMAC, etc.).
    """

    @abstractmethod
    async def authenticate(self, request: APIRequest) -> APIRequest:
        """Add authentication credentials to the request.

        Args:
            request: The outgoing API request to authenticate.

        Returns:
            The request with credentials injected (headers, params, etc.).
        """

    async def refresh(self) -> None:
        """Refresh expired credentials.

        Override this for auth strategies that support token refresh
        (e.g., OAuth2). Default is a no-op for static credentials.
        """

    def is_expired(self) -> bool:
        """Check if credentials need refreshing.

        Returns:
            True if credentials have expired and need a refresh call.
            Default returns False (static credentials never expire).
        """
        return False
