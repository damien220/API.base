"""CircuitBreaker — fail-fast on degraded services."""

from __future__ import annotations

import enum
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ..exceptions.api_exceptions import CircuitOpenError


class CircuitState(str, enum.Enum):
    """Circuit breaker states."""

    CLOSED = "closed"          # Normal operation — requests flow through
    OPEN = "open"              # Failing — reject requests immediately
    HALF_OPEN = "half_open"    # Probing — allow limited requests to test recovery


# Callback type for state transition events
StateChangeCallback = Callable[[str, CircuitState, CircuitState], None]


@dataclass
class CircuitStats:
    """Tracks failure/success counts for a single circuit."""

    failures: int = 0
    successes: int = 0
    consecutive_failures: int = 0
    total_requests: int = 0
    last_failure_time: Optional[float] = None

    def record_success(self) -> None:
        self.successes += 1
        self.consecutive_failures = 0
        self.total_requests += 1

    def record_failure(self) -> None:
        self.failures += 1
        self.consecutive_failures += 1
        self.total_requests += 1
        self.last_failure_time = time.monotonic()

    def reset(self) -> None:
        self.failures = 0
        self.successes = 0
        self.consecutive_failures = 0
        self.total_requests = 0
        self.last_failure_time = None


class CircuitBreaker:
    """Implements the circuit breaker pattern for API resilience.

    Tracks failures per circuit (global or per-endpoint) and transitions
    through three states:

    - **CLOSED**: Requests pass through normally. Failures are counted.
    - **OPEN**: Requests are rejected immediately with ``CircuitOpenError``.
      After ``recovery_timeout`` seconds, transitions to HALF_OPEN.
    - **HALF_OPEN**: A limited number of probe requests are allowed.
      If ``success_threshold`` consecutive successes occur, returns to CLOSED.
      Any failure returns to OPEN.

    Args:
        failure_threshold: Consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait in OPEN before probing (HALF_OPEN).
        success_threshold: Consecutive successes in HALF_OPEN to close the circuit.
        per_endpoint: If True, maintains separate circuits per endpoint.
        on_state_change: Optional callback invoked on state transitions.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
        *,
        per_endpoint: bool = False,
        on_state_change: Optional[StateChangeCallback] = None,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._per_endpoint = per_endpoint
        self._on_state_change = on_state_change
        self._lock = threading.Lock()

        # Global circuit
        self._global_state = CircuitState.CLOSED
        self._global_stats = CircuitStats()
        self._global_opened_at: Optional[float] = None
        self._global_half_open_successes: int = 0

        # Per-endpoint circuits
        self._states: Dict[str, CircuitState] = {}
        self._stats: Dict[str, CircuitStats] = {}
        self._opened_at: Dict[str, float] = {}
        self._half_open_successes: Dict[str, int] = {}

    def check(self, endpoint: Optional[str] = None) -> None:
        """Check if a request is allowed to proceed.

        Args:
            endpoint: Endpoint name for per-endpoint circuit.

        Raises:
            CircuitOpenError: If the circuit is open and the request
                should be rejected.
        """
        state = self._get_state(endpoint)
        name = endpoint or "__global__"

        if state == CircuitState.CLOSED:
            return

        if state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            opened_at = self._get_opened_at(endpoint)
            if opened_at and (time.monotonic() - opened_at) >= self._recovery_timeout:
                self._transition(endpoint, CircuitState.HALF_OPEN)
                return  # Allow probe request
            raise CircuitOpenError(
                f"Circuit breaker is open for '{name}'. "
                f"Recovery in {self._time_until_recovery(endpoint):.1f}s."
            )

        # HALF_OPEN — allow limited probe requests
        return

    def record_success(self, endpoint: Optional[str] = None) -> None:
        """Record a successful request.

        Args:
            endpoint: Endpoint name for per-endpoint circuit.
        """
        with self._lock:
            stats = self._get_stats(endpoint)
            stats.record_success()

            state = self._get_state(endpoint)
            if state == CircuitState.HALF_OPEN:
                successes = self._increment_half_open_successes(endpoint)
                if successes >= self._success_threshold:
                    self._transition(endpoint, CircuitState.CLOSED)

    def record_failure(self, endpoint: Optional[str] = None) -> None:
        """Record a failed request.

        Args:
            endpoint: Endpoint name for per-endpoint circuit.
        """
        with self._lock:
            stats = self._get_stats(endpoint)
            stats.record_failure()

            state = self._get_state(endpoint)
            if state == CircuitState.HALF_OPEN:
                # Any failure in half-open → reopen
                self._transition(endpoint, CircuitState.OPEN)
            elif state == CircuitState.CLOSED:
                if stats.consecutive_failures >= self._failure_threshold:
                    self._transition(endpoint, CircuitState.OPEN)

    def get_state(self, endpoint: Optional[str] = None) -> CircuitState:
        """Return the current state of the circuit."""
        return self._get_state(endpoint)

    def get_stats(self, endpoint: Optional[str] = None) -> CircuitStats:
        """Return a copy of the circuit statistics."""
        stats = self._get_stats(endpoint)
        from dataclasses import replace
        return replace(stats)

    def reset(self, endpoint: Optional[str] = None) -> None:
        """Force-reset the circuit to CLOSED with clean stats."""
        with self._lock:
            self._transition(endpoint, CircuitState.CLOSED)
            self._get_stats(endpoint).reset()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_state(self, endpoint: Optional[str]) -> CircuitState:
        if endpoint and self._per_endpoint:
            return self._states.get(endpoint, CircuitState.CLOSED)
        return self._global_state

    def _set_state(self, endpoint: Optional[str], state: CircuitState) -> None:
        if endpoint and self._per_endpoint:
            self._states[endpoint] = state
        else:
            self._global_state = state

    def _get_stats(self, endpoint: Optional[str]) -> CircuitStats:
        if endpoint and self._per_endpoint:
            if endpoint not in self._stats:
                self._stats[endpoint] = CircuitStats()
            return self._stats[endpoint]
        return self._global_stats

    def _get_opened_at(self, endpoint: Optional[str]) -> Optional[float]:
        if endpoint and self._per_endpoint:
            return self._opened_at.get(endpoint)
        return self._global_opened_at

    def _set_opened_at(self, endpoint: Optional[str], t: Optional[float]) -> None:
        if endpoint and self._per_endpoint:
            if t is not None:
                self._opened_at[endpoint] = t
            elif endpoint in self._opened_at:
                del self._opened_at[endpoint]
        else:
            self._global_opened_at = t

    def _increment_half_open_successes(self, endpoint: Optional[str]) -> int:
        if endpoint and self._per_endpoint:
            self._half_open_successes[endpoint] = (
                self._half_open_successes.get(endpoint, 0) + 1
            )
            return self._half_open_successes[endpoint]
        self._global_half_open_successes += 1
        return self._global_half_open_successes

    def _reset_half_open_successes(self, endpoint: Optional[str]) -> None:
        if endpoint and self._per_endpoint:
            self._half_open_successes[endpoint] = 0
        else:
            self._global_half_open_successes = 0

    def _transition(self, endpoint: Optional[str], new_state: CircuitState) -> None:
        """Perform a state transition and fire the callback."""
        old_state = self._get_state(endpoint)
        if old_state == new_state:
            return

        self._set_state(endpoint, new_state)
        name = endpoint or "__global__"

        if new_state == CircuitState.OPEN:
            self._set_opened_at(endpoint, time.monotonic())
            self._reset_half_open_successes(endpoint)
        elif new_state == CircuitState.CLOSED:
            self._set_opened_at(endpoint, None)
            self._get_stats(endpoint).reset()
            self._reset_half_open_successes(endpoint)
        elif new_state == CircuitState.HALF_OPEN:
            self._reset_half_open_successes(endpoint)

        if self._on_state_change:
            try:
                self._on_state_change(name, old_state, new_state)
            except Exception:
                pass  # Don't let callback errors break the circuit breaker

    def _time_until_recovery(self, endpoint: Optional[str]) -> float:
        opened_at = self._get_opened_at(endpoint)
        if opened_at is None:
            return 0.0
        elapsed = time.monotonic() - opened_at
        return max(0.0, self._recovery_timeout - elapsed)
