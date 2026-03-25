"""Optional integration with Cache_Manager for API response caching."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..utils.serialization import build_cache_key

# Attempt to import cache_manager — graceful degradation if not installed
try:
    from cache_manager import (
        AbstractCache,
        CacheNamespace,
        CacheStats,
        get_cache,
    )

    _HAS_CACHE_MGR = True
except ImportError:
    _HAS_CACHE_MGR = False


def is_available() -> bool:
    """Check if Cache_Manager is installed and importable."""
    return _HAS_CACHE_MGR


class APIResponseCache:
    """Caches API responses using Cache_Manager.

    Provides per-client namespace isolation and automatic cache key
    generation from request components (method + URL + params + body hash).

    Args:
        namespace: Namespace prefix for cache keys (e.g., "api:openai").
        backend: Cache backend name (default: "memory").
        default_ttl: Default TTL in seconds for cached entries.
        cache_config: Extra kwargs passed to ``get_cache()``.
    """

    def __init__(
        self,
        namespace: str = "api",
        *,
        backend: str = "memory",
        default_ttl: int = 300,
        cache_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not _HAS_CACHE_MGR:
            raise RuntimeError(
                "Cache_Manager is not installed. "
                "Install it to use API response caching."
            )

        config = cache_config or {}
        self._cache: AbstractCache = get_cache(backend, **config)
        self._namespace = CacheNamespace(self._cache, namespace)
        self._default_ttl = default_ttl

    def make_key(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
    ) -> str:
        """Generate a deterministic cache key from request components.

        Args:
            method: HTTP method.
            url: Full request URL.
            params: Query parameters.
            body: Request body.

        Returns:
            Cache key string.
        """
        return build_cache_key(method, url, params, body)

    def get(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
    ) -> Optional[Any]:
        """Look up a cached response.

        Args:
            method: HTTP method.
            url: Full request URL.
            params: Query parameters.
            body: Request body.

        Returns:
            Cached response data, or None if not found.
        """
        key = self.make_key(method, url, params, body)
        return self._namespace.get(key)

    def set(
        self,
        method: str,
        url: str,
        response_data: Any,
        *,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
        ttl: Optional[int] = None,
    ) -> None:
        """Cache a response.

        Args:
            method: HTTP method.
            url: Full request URL.
            response_data: Response data to cache (typically the parsed body).
            params: Query parameters.
            body: Request body.
            ttl: TTL in seconds. None uses the default.
        """
        key = self.make_key(method, url, params, body)
        self._namespace.set(key, response_data, ttl=ttl or self._default_ttl)

    def invalidate(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        body: Any = None,
    ) -> None:
        """Remove a specific cached response.

        Args:
            method: HTTP method.
            url: Full request URL.
            params: Query parameters.
            body: Request body.
        """
        key = self.make_key(method, url, params, body)
        self._namespace.delete(key)

    def clear(self) -> None:
        """Clear all cached responses in this namespace."""
        self._cache.clear()

    def get_stats(self) -> Any:
        """Return cache hit/miss statistics.

        Returns:
            CacheStats object if available, or None.
        """
        return self._cache.get_stats()

    @property
    def namespace(self) -> str:
        """The cache namespace prefix."""
        return self._namespace._prefix if hasattr(self._namespace, '_prefix') else self._namespace.namespace

    def connect(self) -> None:
        """Connect the underlying cache backend."""
        self._cache.connect()

    def disconnect(self) -> None:
        """Disconnect the underlying cache backend."""
        self._cache.disconnect()


def create_response_cache(
    namespace: str = "api",
    **kwargs: Any,
) -> Optional[APIResponseCache]:
    """Factory: create an APIResponseCache if Cache_Manager is available.

    Returns None (instead of raising) if Cache_Manager is not installed,
    allowing callers to handle the optional dependency gracefully.

    Args:
        namespace: Namespace prefix for cache keys.
        **kwargs: Passed to ``APIResponseCache.__init__``.

    Returns:
        APIResponseCache instance, or None if unavailable.
    """
    if not _HAS_CACHE_MGR:
        return None
    return APIResponseCache(namespace, **kwargs)
