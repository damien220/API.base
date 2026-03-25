"""OAuth2 authentication strategy with client credentials and authorization code flows."""

from __future__ import annotations

import threading
import time
from enum import Enum
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx

from .base import AbstractAuthStrategy
from ..request.models import APIRequest


class OAuth2Flow(str, Enum):
    """Supported OAuth2 grant types."""

    CLIENT_CREDENTIALS = "client_credentials"
    AUTHORIZATION_CODE = "authorization_code"
    REFRESH_TOKEN = "refresh_token"


class OAuth2Auth(AbstractAuthStrategy):
    """OAuth2 authentication with automatic token management.

    Supports two primary flows:

    **Client Credentials** (machine-to-machine)::

        auth = OAuth2Auth(
            token_url="https://auth.example.com/oauth/token",
            client_id="my-client-id",
            client_secret="my-secret",
            flow=OAuth2Flow.CLIENT_CREDENTIALS,
        )

    **Authorization Code** (user-delegated, pre-obtained tokens)::

        auth = OAuth2Auth(
            token_url="https://auth.example.com/oauth/token",
            client_id="my-client-id",
            client_secret="my-secret",
            flow=OAuth2Flow.AUTHORIZATION_CODE,
            access_token="existing-access-token",
            refresh_token_value="existing-refresh-token",
        )

    Args:
        token_url: OAuth2 token endpoint URL.
        client_id: OAuth2 client ID.
        client_secret: OAuth2 client secret.
        flow: OAuth2 grant type.
        scopes: List of requested scopes.
        access_token: Pre-existing access token (for auth code flow).
        refresh_token_value: Pre-existing refresh token.
        expires_at: Unix timestamp when the current token expires.
        refresh_buffer: Seconds before expiry to trigger proactive refresh.
        extra_params: Additional parameters to include in token requests.
        token_request_callback: Optional async callback for custom token requests.
    """

    def __init__(
        self,
        token_url: str,
        client_id: str,
        client_secret: str,
        *,
        flow: OAuth2Flow = OAuth2Flow.CLIENT_CREDENTIALS,
        scopes: Optional[list[str]] = None,
        access_token: Optional[str] = None,
        refresh_token_value: Optional[str] = None,
        expires_at: Optional[float] = None,
        refresh_buffer: float = 30.0,
        extra_params: Optional[Dict[str, str]] = None,
        token_request_callback: Optional[
            Callable[..., Awaitable[Dict[str, Any]]]
        ] = None,
    ) -> None:
        self._token_url = token_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._flow = flow
        self._scopes = scopes or []
        self._access_token = access_token
        self._refresh_token = refresh_token_value
        self._expires_at = expires_at
        self._refresh_buffer = refresh_buffer
        self._extra_params = extra_params or {}
        self._token_request_callback = token_request_callback
        self._lock = threading.Lock()

    async def authenticate(self, request: APIRequest) -> APIRequest:
        """Inject the OAuth2 Bearer token into the request.

        Automatically refreshes the token if expired or not yet obtained.
        """
        if self._access_token is None or self.is_expired():
            await self.refresh()

        request.headers["Authorization"] = f"Bearer {self._access_token}"
        return request

    async def refresh(self) -> None:
        """Obtain or refresh the access token.

        For CLIENT_CREDENTIALS: requests a new token every time.
        For AUTHORIZATION_CODE: uses the refresh token if available,
        otherwise falls back to the custom callback.
        """
        if self._token_request_callback is not None:
            token_data = await self._token_request_callback()
        elif self._flow == OAuth2Flow.CLIENT_CREDENTIALS:
            token_data = await self._request_client_credentials()
        elif self._refresh_token is not None:
            token_data = await self._request_refresh_token()
        else:
            raise RuntimeError(
                "Cannot refresh OAuth2 token: no refresh token or callback available. "
                "For authorization_code flow, provide a refresh_token_value or "
                "token_request_callback."
            )

        self._apply_token_response(token_data)

    def is_expired(self) -> bool:
        """Check if the access token has expired or is about to expire."""
        if self._access_token is None:
            return True
        if self._expires_at is None:
            return False
        return time.time() >= (self._expires_at - self._refresh_buffer)

    def set_tokens(
        self,
        access_token: str,
        *,
        refresh_token: Optional[str] = None,
        expires_at: Optional[float] = None,
    ) -> None:
        """Manually set tokens (thread-safe).

        Args:
            access_token: New access token.
            refresh_token: New refresh token.
            expires_at: Unix timestamp when the token expires.
        """
        with self._lock:
            self._access_token = access_token
            if refresh_token is not None:
                self._refresh_token = refresh_token
            self._expires_at = expires_at

    @property
    def has_refresh_token(self) -> bool:
        """Whether a refresh token is available."""
        return self._refresh_token is not None

    @property
    def redacted_token(self) -> str:
        """Return a redacted version of the access token for logging."""
        if not self._access_token or len(self._access_token) <= 8:
            return "***"
        return f"{self._access_token[:4]}...{self._access_token[-4:]}"

    # ------------------------------------------------------------------
    # Token request methods
    # ------------------------------------------------------------------

    async def _request_client_credentials(self) -> Dict[str, Any]:
        """Request a token using the client_credentials grant."""
        data: Dict[str, str] = {
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            **self._extra_params,
        }
        if self._scopes:
            data["scope"] = " ".join(self._scopes)

        return await self._post_token_request(data)

    async def _request_refresh_token(self) -> Dict[str, Any]:
        """Request a new token using the refresh_token grant."""
        data: Dict[str, str] = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token or "",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            **self._extra_params,
        }

        return await self._post_token_request(data)

    async def _post_token_request(self, data: Dict[str, str]) -> Dict[str, Any]:
        """Send a POST request to the token endpoint.

        Uses a standalone httpx.AsyncClient to avoid circular dependency
        on the API client itself.
        """
        async with httpx.AsyncClient() as http:
            response = await http.post(
                self._token_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"OAuth2 token request failed (HTTP {response.status_code}): "
                f"{response.text[:300]}"
            )

        return response.json()

    def _apply_token_response(self, token_data: Dict[str, Any]) -> None:
        """Extract and store tokens from the OAuth2 token response."""
        with self._lock:
            self._access_token = token_data["access_token"]

            if "refresh_token" in token_data:
                self._refresh_token = token_data["refresh_token"]

            if "expires_in" in token_data:
                self._expires_at = time.time() + int(token_data["expires_in"])
            elif "expires_at" in token_data:
                self._expires_at = float(token_data["expires_at"])
            else:
                self._expires_at = None
