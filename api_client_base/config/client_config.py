"""Configuration dataclasses for API client setup."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Optional

from ..types import RetryBackoff

if TYPE_CHECKING:
    from ..auth.base import AbstractAuthStrategy


@dataclass
class RateLimitConfig:
    """Rate limiting configuration."""

    max_requests: int = 60
    period_seconds: float = 60.0
    per_endpoint: bool = False


@dataclass
class CircuitBreakerConfig:
    """Circuit breaker configuration."""

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    success_threshold: int = 2
    per_endpoint: bool = False


@dataclass
class APIClientConfig:
    """Configuration for an API client instance."""

    base_url: str
    auth_strategy: Optional[AbstractAuthStrategy] = None
    api_version: Optional[str] = None

    # Timeouts
    timeout: float = 30.0
    connect_timeout: float = 10.0

    # Retry
    max_retries: int = 3
    retry_backoff: RetryBackoff = RetryBackoff.EXPONENTIAL_JITTER
    retry_base_delay: float = 1.0
    retry_max_delay: float = 60.0

    # Rate limiting
    rate_limit: Optional[RateLimitConfig] = None

    # Circuit breaker
    circuit_breaker: Optional[CircuitBreakerConfig] = None

    # HTTP settings
    user_agent: str = "api-client-base/0.1.0"
    default_headers: Dict[str, str] = field(default_factory=dict)
    verify_ssl: bool = True
    proxy: Optional[str] = None
    follow_redirects: bool = True

    # Caching (optional integration with Cache_Manager)
    cache_enabled: bool = False
    cache_config: Optional[Dict[str, Any]] = None

    # Logging (optional integration with Logger_Package)
    logging_enabled: bool = True
    log_request_body: bool = False
    log_response_body: bool = False
