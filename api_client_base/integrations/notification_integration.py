"""Optional integration with Notification_Manager for critical API failure alerting."""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from ..resilience.circuit_breaker import CircuitState

# Attempt to import notification_manager — graceful degradation if not installed
try:
    from notification_manager import Notification, Recipient
    from notification_manager.models import Priority

    _HAS_NOTIFICATION_MGR = True
except ImportError:
    _HAS_NOTIFICATION_MGR = False


def is_available() -> bool:
    """Check if Notification_Manager is installed and importable."""
    return _HAS_NOTIFICATION_MGR


class APIAlertManager:
    """Sends throttled notifications on critical API failures.

    Integrates with Notification_Manager to alert operators when:
    - A circuit breaker opens (service degraded)
    - Authentication fails repeatedly (credential rotation needed)
    - Rate limits are exhausted (quota management)
    - Consecutive server errors exceed a threshold

    Notifications are throttled using idempotency keys with TTLs
    to avoid alert spam.

    Args:
        notification_manager: A started NotificationManager instance.
        recipient_id: Recipient ID for alerts.
        channel_hint: Preferred notification channel (e.g., "slack", "email").
        throttle_seconds: Minimum seconds between duplicate alerts.
        api_name: Name of the API service for alert context.
    """

    def __init__(
        self,
        notification_manager: Any,
        *,
        recipient_id: str = "ops-team",
        channel_hint: Optional[str] = None,
        throttle_seconds: int = 300,
        api_name: str = "api",
    ) -> None:
        if not _HAS_NOTIFICATION_MGR:
            raise RuntimeError(
                "Notification_Manager is not installed. "
                "Install it to use API alerting."
            )
        self._manager = notification_manager
        self._recipient_id = recipient_id
        self._channel_hint = channel_hint
        self._throttle_seconds = throttle_seconds
        self._api_name = api_name
        self._last_sent: Dict[str, float] = {}

    async def alert_circuit_open(
        self, endpoint: Optional[str] = None
    ) -> bool:
        """Send an alert when a circuit breaker transitions to OPEN.

        Args:
            endpoint: The endpoint whose circuit opened.

        Returns:
            True if the notification was sent, False if throttled.
        """
        target = endpoint or "global"
        return await self._send(
            title=f"[{self._api_name}] Circuit Breaker OPEN — {target}",
            body=(
                f"The circuit breaker for '{target}' has opened due to "
                f"consecutive failures. Requests are being rejected. "
                f"Investigate the upstream service."
            ),
            priority=Priority.HIGH,
            idempotency_prefix="circuit_open",
            idempotency_suffix=target,
        )

    async def alert_auth_failure(
        self, error_message: str = ""
    ) -> bool:
        """Send an alert on repeated authentication failures.

        Args:
            error_message: The auth error message.

        Returns:
            True if sent, False if throttled.
        """
        return await self._send(
            title=f"[{self._api_name}] Authentication Failure",
            body=(
                f"Repeated authentication failures detected. "
                f"Credentials may need rotation. Error: {error_message}"
            ),
            priority=Priority.HIGH,
            idempotency_prefix="auth_failure",
        )

    async def alert_rate_limit(
        self,
        *,
        retry_after: Optional[float] = None,
        endpoint: Optional[str] = None,
    ) -> bool:
        """Send an alert when rate limits are exhausted.

        Args:
            retry_after: Seconds until rate limit resets.
            endpoint: The affected endpoint.

        Returns:
            True if sent, False if throttled.
        """
        target = endpoint or "global"
        retry_info = f" Retry after {retry_after:.0f}s." if retry_after else ""
        return await self._send(
            title=f"[{self._api_name}] Rate Limit Exhausted — {target}",
            body=(
                f"API rate limit exceeded for '{target}'.{retry_info} "
                f"Consider reducing request volume or upgrading the plan."
            ),
            priority=Priority.NORMAL,
            idempotency_prefix="rate_limit",
            idempotency_suffix=target,
        )

    async def alert_server_errors(
        self,
        consecutive_count: int,
        *,
        endpoint: Optional[str] = None,
    ) -> bool:
        """Send an alert on consecutive server errors.

        Args:
            consecutive_count: Number of consecutive 5xx errors.
            endpoint: The affected endpoint.

        Returns:
            True if sent, False if throttled.
        """
        target = endpoint or "global"
        return await self._send(
            title=f"[{self._api_name}] Server Errors — {target}",
            body=(
                f"{consecutive_count} consecutive server errors (5xx) "
                f"detected for '{target}'. The upstream service may be "
                f"experiencing an outage."
            ),
            priority=Priority.HIGH if consecutive_count >= 10 else Priority.NORMAL,
            idempotency_prefix="server_errors",
            idempotency_suffix=target,
        )

    def circuit_breaker_callback(
        self, name: str, old_state: CircuitState, new_state: CircuitState
    ) -> None:
        """Callback for CircuitBreaker state transitions.

        Pass this method as ``on_state_change`` when creating a CircuitBreaker
        to automatically receive alerts on state changes.

        Note: This is a sync callback. It schedules the async alert
        without blocking.

        Args:
            name: Circuit name (endpoint or "__global__").
            old_state: Previous circuit state.
            new_state: New circuit state.
        """
        if new_state == CircuitState.OPEN:
            import asyncio

            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.alert_circuit_open(name))
            except RuntimeError:
                pass  # No running event loop — skip async notification

    async def _send(
        self,
        title: str,
        body: str,
        priority: Any,
        idempotency_prefix: str,
        idempotency_suffix: str = "",
    ) -> bool:
        """Send a throttled notification.

        Returns False if the same alert was sent within the throttle window.
        """
        idem_key = self._make_idempotency_key(idempotency_prefix, idempotency_suffix)

        # Throttle check
        now = time.monotonic()
        last = self._last_sent.get(idem_key, 0)
        if (now - last) < self._throttle_seconds:
            return False

        notification = Notification(
            title=title,
            body=body,
            recipient=Recipient(id=self._recipient_id),
            channel_hint=self._channel_hint,
            priority=priority,
            idempotency_key=idem_key,
        )

        try:
            await self._manager.send(notification)
            self._last_sent[idem_key] = now
            return True
        except Exception:
            return False

    def _make_idempotency_key(self, prefix: str, suffix: str = "") -> str:
        """Create a deterministic idempotency key."""
        raw = f"{self._api_name}:{prefix}:{suffix}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


def create_alert_manager(
    notification_manager: Any,
    **kwargs: Any,
) -> Optional[APIAlertManager]:
    """Factory: create an APIAlertManager if Notification_Manager is available.

    Returns None (instead of raising) if Notification_Manager is not installed.

    Args:
        notification_manager: A started NotificationManager instance.
        **kwargs: Passed to ``APIAlertManager.__init__``.

    Returns:
        APIAlertManager instance, or None if unavailable.
    """
    if not _HAS_NOTIFICATION_MGR:
        return None
    return APIAlertManager(notification_manager, **kwargs)
