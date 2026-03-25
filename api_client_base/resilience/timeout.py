"""TimeoutPolicy — per-request and per-endpoint timeout management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class TimeoutPolicy:
    """Manages timeout values for API requests.

    Provides a layered timeout resolution:
    1. Per-request explicit timeout (highest priority)
    2. Per-endpoint configured timeout
    3. Global default timeout (lowest priority)

    Args:
        default_timeout: Global default request timeout in seconds.
        default_connect_timeout: Global default connection timeout in seconds.
        endpoint_timeouts: Per-endpoint timeout overrides.
    """

    default_timeout: float = 30.0
    default_connect_timeout: float = 10.0
    endpoint_timeouts: Dict[str, float] = field(default_factory=dict)
    endpoint_connect_timeouts: Dict[str, float] = field(default_factory=dict)

    def resolve_timeout(
        self,
        *,
        request_timeout: Optional[float] = None,
        endpoint: Optional[str] = None,
    ) -> float:
        """Resolve the effective timeout for a request.

        Priority: request_timeout > endpoint override > global default.

        Args:
            request_timeout: Explicit per-request timeout.
            endpoint: Endpoint name for per-endpoint lookup.

        Returns:
            Timeout in seconds.
        """
        if request_timeout is not None:
            return request_timeout
        if endpoint and endpoint in self.endpoint_timeouts:
            return self.endpoint_timeouts[endpoint]
        return self.default_timeout

    def resolve_connect_timeout(
        self,
        *,
        endpoint: Optional[str] = None,
    ) -> float:
        """Resolve the connection timeout for a request.

        Priority: endpoint override > global default.

        Args:
            endpoint: Endpoint name for per-endpoint lookup.

        Returns:
            Connection timeout in seconds.
        """
        if endpoint and endpoint in self.endpoint_connect_timeouts:
            return self.endpoint_connect_timeouts[endpoint]
        return self.default_connect_timeout

    def set_endpoint_timeout(
        self,
        endpoint: str,
        timeout: float,
        connect_timeout: Optional[float] = None,
    ) -> None:
        """Configure a custom timeout for a specific endpoint.

        Args:
            endpoint: Endpoint name.
            timeout: Request timeout in seconds.
            connect_timeout: Optional connection timeout in seconds.
        """
        self.endpoint_timeouts[endpoint] = timeout
        if connect_timeout is not None:
            self.endpoint_connect_timeouts[endpoint] = connect_timeout

    def remove_endpoint_timeout(self, endpoint: str) -> None:
        """Remove per-endpoint timeout override (falls back to default)."""
        self.endpoint_timeouts.pop(endpoint, None)
        self.endpoint_connect_timeouts.pop(endpoint, None)
