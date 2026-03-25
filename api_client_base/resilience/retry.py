"""RetryPolicy — configurable retry logic with backoff strategies."""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Optional, Set

from ..types import RETRIABLE_STATUS_CODES, RetryBackoff


@dataclass
class RetryPolicy:
    """Determines whether and how to retry failed requests.

    Supports fixed, exponential, and exponential-with-jitter backoff.
    Respects ``Retry-After`` headers when available.

    Args:
        max_retries: Maximum number of retry attempts (0 = no retries).
        backoff: Backoff strategy between retries.
        base_delay: Base delay in seconds for backoff calculation.
        max_delay: Maximum delay cap in seconds.
        retriable_status_codes: HTTP status codes eligible for retry.
        retry_on_connection_error: Whether to retry on connection failures.
        retry_on_timeout: Whether to retry on timeout errors.
    """

    max_retries: int = 3
    backoff: RetryBackoff = RetryBackoff.EXPONENTIAL_JITTER
    base_delay: float = 1.0
    max_delay: float = 60.0
    retriable_status_codes: Set[int] = field(
        default_factory=lambda: set(RETRIABLE_STATUS_CODES)
    )
    retry_on_connection_error: bool = True
    retry_on_timeout: bool = True

    def should_retry(
        self,
        attempt: int,
        *,
        status_code: Optional[int] = None,
        is_connection_error: bool = False,
        is_timeout: bool = False,
    ) -> bool:
        """Decide whether a request should be retried.

        Args:
            attempt: Current attempt number (1-based).
            status_code: HTTP status code from the response, if any.
            is_connection_error: Whether the failure was a connection error.
            is_timeout: Whether the failure was a timeout.

        Returns:
            True if the request should be retried.
        """
        if attempt > self.max_retries:
            return False

        if status_code is not None and status_code in self.retriable_status_codes:
            return True

        if is_connection_error and self.retry_on_connection_error:
            return True

        if is_timeout and self.retry_on_timeout:
            return True

        return False

    def get_delay(
        self, attempt: int, retry_after: Optional[float] = None
    ) -> float:
        """Calculate the delay before the next retry attempt.

        Args:
            attempt: Current attempt number (1-based).
            retry_after: Value from Retry-After header (seconds).

        Returns:
            Delay in seconds before the next retry.
        """
        if self.backoff == RetryBackoff.FIXED:
            delay = self.base_delay
        elif self.backoff == RetryBackoff.EXPONENTIAL:
            delay = self.base_delay * (2 ** (attempt - 1))
        else:  # EXPONENTIAL_JITTER
            delay = self.base_delay * (2 ** (attempt - 1))
            delay *= 0.5 + random.random()

        # Respect Retry-After header
        if retry_after is not None:
            delay = max(delay, retry_after)

        return min(delay, self.max_delay)

    async def wait(
        self, attempt: int, retry_after: Optional[float] = None
    ) -> None:
        """Sleep for the calculated backoff delay.

        Args:
            attempt: Current attempt number (1-based).
            retry_after: Value from Retry-After header (seconds).
        """
        delay = self.get_delay(attempt, retry_after)
        await asyncio.sleep(delay)
