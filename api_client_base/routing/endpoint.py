"""EndpointDefinition — declarative API endpoint descriptor."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Type

from ..types import HttpMethod


@dataclass
class EndpointDefinition:
    """Describes a single API endpoint.

    Used by ``EndpointRegistry`` to store, resolve, and validate
    endpoint metadata. Concrete clients register their endpoints
    at init time and look them up by name when making requests.

    Args:
        name: Unique identifier (e.g., "create_completion").
        path: URL path template (e.g., "/users/{user_id}/posts").
        method: HTTP method. Defaults to GET.
        auth_required: Whether authentication is needed. Defaults to True.
        rate_limit_override: Per-endpoint max requests/period override.
        timeout: Per-endpoint timeout in seconds. None = use client default.
        cache_ttl: Cache TTL in seconds. None = no caching.
        response_model: Optional type for automatic response deserialization.
        description: Human-readable description of the endpoint.
        group: Logical grouping / resource name (e.g., "users", "chat").
        retry_override: Per-endpoint max retries. None = use client default.
        metadata: Arbitrary extra data attached to the endpoint.
    """

    name: str
    path: str
    method: str = HttpMethod.GET.value
    auth_required: bool = True
    rate_limit_override: Optional[int] = None
    timeout: Optional[float] = None
    cache_ttl: Optional[int] = None
    response_model: Optional[Type[Any]] = None
    description: str = ""
    group: str = ""
    retry_override: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def resolve_path(self, **path_params: Any) -> str:
        """Substitute path parameters into the path template.

        Example::

            ep = EndpointDefinition(name="get_user", path="/users/{user_id}")
            ep.resolve_path(user_id=42)  # → "/users/42"

        Raises:
            KeyError: If a required path parameter is missing.
        """
        try:
            return self.path.format(**path_params)
        except KeyError as exc:
            raise KeyError(
                f"Missing path parameter {exc} for endpoint '{self.name}' "
                f"(path: {self.path})"
            ) from exc

    @property
    def path_params(self) -> list[str]:
        """Return the list of path parameter names from the template."""
        import re
        return re.findall(r"\{(\w+)\}", self.path)

    def __post_init__(self) -> None:
        self.method = self.method.upper()
        if not self.name:
            raise ValueError("EndpointDefinition.name cannot be empty")
        if not self.path:
            raise ValueError("EndpointDefinition.path cannot be empty")
