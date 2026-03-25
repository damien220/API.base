"""RateLimiter — token bucket rate limiting for API requests."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from ..exceptions.api_exceptions import RateLimitError


@dataclass
class RateLimitState:
    """Internal state for a single rate limit bucket."""

    tokens: float
    max_tokens: float
    refill_rate: float  # tokens per second
    last_refill: float = field(default_factory=time.monotonic)

    def refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self.last_refill
        self.tokens = min(self.max_tokens, self.tokens + elapsed * self.refill_rate)
        self.last_refill = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Try to consume tokens. Returns True if allowed."""
        self.refill()
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def wait_time(self) -> float:
        """Seconds until at least one token is available."""
        self.refill()
        if self.tokens >= 1.0:
            return 0.0
        return (1.0 - self.tokens) / self.refill_rate


class RateLimiter:
    """Token bucket rate limiter for API requests.

    Supports per-client and per-endpoint rate limits. Can also
    parse and respect API rate limit headers from responses.

    Args:
        max_requests: Maximum requests allowed per period.
        period: Time period in seconds.
        per_endpoint: If True, maintains separate buckets per endpoint.
    """

    def __init__(
        self,
        max_requests: int = 60,
        period: float = 60.0,
        *,
        per_endpoint: bool = False,
    ) -> None:
        self._max_requests = max_requests
        self._period = period
        self._per_endpoint = per_endpoint
        self._lock = threading.Lock()

        refill_rate = max_requests / period
        self._global_bucket = RateLimitState(
            tokens=float(max_requests),
            max_tokens=float(max_requests),
            refill_rate=refill_rate,
        )
        self._endpoint_buckets: Dict[str, RateLimitState] = {}

    async def acquire(self, endpoint: Optional[str] = None) -> None:
        """Wait until a request is allowed, then consume a token.

        Args:
            endpoint: Endpoint name for per-endpoint limiting.

        Raises:
            RateLimitError: If waiting would exceed a reasonable threshold.
        """
        bucket = self._get_bucket(endpoint)

        with self._lock:
            if bucket.try_acquire():
                return

        # Wait and retry
        wait = bucket.wait_time
        if wait > self._period:
            raise RateLimitError(
                "Rate limit exceeded — wait time too long",
                retry_after=wait,
                limit=self._max_requests,
                remaining=0,
            )

        await asyncio.sleep(wait)

        with self._lock:
            bucket.try_acquire()

    def try_acquire(self, endpoint: Optional[str] = None) -> bool:
        """Try to acquire a token without waiting.

        Args:
            endpoint: Endpoint name for per-endpoint limiting.

        Returns:
            True if the request is allowed, False if rate limited.
        """
        bucket = self._get_bucket(endpoint)
        with self._lock:
            return bucket.try_acquire()

    def update_from_headers(
        self,
        headers: Dict[str, str],
        endpoint: Optional[str] = None,
    ) -> None:
        """Update rate limit state from API response headers.

        Recognizes common rate limit headers:
        - ``X-RateLimit-Remaining``
        - ``X-RateLimit-Limit``
        - ``X-RateLimit-Reset``

        Args:
            headers: Response headers dict.
            endpoint: Endpoint name for per-endpoint bucket.
        """
        remaining = _parse_header_int(headers, "X-RateLimit-Remaining")
        limit = _parse_header_int(headers, "X-RateLimit-Limit")
        reset = _parse_header_float(headers, "X-RateLimit-Reset")

        if remaining is None and limit is None:
            return

        bucket = self._get_bucket(endpoint)
        with self._lock:
            if remaining is not None:
                bucket.tokens = min(float(remaining), bucket.max_tokens)
            if limit is not None:
                bucket.max_tokens = float(limit)
                if reset is not None:
                    time_until_reset = max(0.0, reset - time.time())
                    if time_until_reset > 0:
                        bucket.refill_rate = float(limit) / time_until_reset

    def set_endpoint_limit(
        self,
        endpoint: str,
        max_requests: int,
        period: float = 60.0,
    ) -> None:
        """Configure a custom rate limit for a specific endpoint.

        Args:
            endpoint: Endpoint name.
            max_requests: Maximum requests per period.
            period: Time period in seconds.
        """
        refill_rate = max_requests / period
        with self._lock:
            self._endpoint_buckets[endpoint] = RateLimitState(
                tokens=float(max_requests),
                max_tokens=float(max_requests),
                refill_rate=refill_rate,
            )

    @property
    def remaining(self) -> float:
        """Approximate remaining tokens in the global bucket."""
        self._global_bucket.refill()
        return self._global_bucket.tokens

    def _get_bucket(self, endpoint: Optional[str]) -> RateLimitState:
        """Return the appropriate bucket for the request."""
        if endpoint and self._per_endpoint:
            if endpoint in self._endpoint_buckets:
                return self._endpoint_buckets[endpoint]
        return self._global_bucket


def _parse_header_int(headers: Dict[str, str], name: str) -> Optional[int]:
    """Parse an integer header value, case-insensitive."""
    for key, val in headers.items():
        if key.lower() == name.lower():
            try:
                return int(val)
            except (ValueError, TypeError):
                return None
    return None


def _parse_header_float(headers: Dict[str, str], name: str) -> Optional[float]:
    """Parse a float header value, case-insensitive."""
    for key, val in headers.items():
        if key.lower() == name.lower():
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
    return None
