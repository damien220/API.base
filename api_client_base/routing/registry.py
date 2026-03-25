"""EndpointRegistry — stores and resolves endpoint definitions."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .endpoint import EndpointDefinition


class EndpointRegistry:
    """Registry for managing API endpoint definitions.

    Concrete clients register their endpoints at init time and
    look them up by name when making requests::

        registry = EndpointRegistry()
        registry.register(EndpointDefinition(
            name="list_users",
            path="/users",
            method="GET",
        ))

        ep = registry.get("list_users")
    """

    def __init__(self) -> None:
        self._endpoints: Dict[str, EndpointDefinition] = {}

    def register(self, endpoint: EndpointDefinition) -> None:
        """Register an endpoint definition.

        Args:
            endpoint: The endpoint to register.

        Raises:
            ValueError: If an endpoint with the same name is already registered.
        """
        if endpoint.name in self._endpoints:
            raise ValueError(
                f"Endpoint '{endpoint.name}' is already registered"
            )
        self._endpoints[endpoint.name] = endpoint

    def register_many(self, *endpoints: EndpointDefinition) -> None:
        """Register multiple endpoints at once."""
        for ep in endpoints:
            self.register(ep)

    def get(self, name: str) -> EndpointDefinition:
        """Retrieve an endpoint by name.

        Args:
            name: The endpoint name.

        Returns:
            The EndpointDefinition.

        Raises:
            KeyError: If the endpoint is not registered.
        """
        try:
            return self._endpoints[name]
        except KeyError:
            available = ", ".join(sorted(self._endpoints.keys())) or "(none)"
            raise KeyError(
                f"Endpoint '{name}' not found. Available: {available}"
            )

    def resolve(self, name: str, **path_params: Any) -> EndpointDefinition:
        """Get an endpoint and resolve its path parameters.

        Returns a *copy* of the endpoint with the path resolved,
        leaving the original template intact in the registry.

        Args:
            name: The endpoint name.
            **path_params: Values for path template parameters.

        Returns:
            A new EndpointDefinition with the resolved path.
        """
        ep = self.get(name)
        if not path_params:
            return ep
        from dataclasses import replace
        return replace(ep, path=ep.resolve_path(**path_params))

    def unregister(self, name: str) -> None:
        """Remove an endpoint from the registry.

        Raises:
            KeyError: If the endpoint is not registered.
        """
        if name not in self._endpoints:
            raise KeyError(f"Endpoint '{name}' not found")
        del self._endpoints[name]

    def has(self, name: str) -> bool:
        """Check if an endpoint is registered."""
        return name in self._endpoints

    def list_endpoints(self) -> List[EndpointDefinition]:
        """Return all registered endpoints."""
        return list(self._endpoints.values())

    def list_names(self) -> List[str]:
        """Return all registered endpoint names."""
        return list(self._endpoints.keys())

    def get_by_group(self, group: str) -> List[EndpointDefinition]:
        """Return all endpoints belonging to a group."""
        return [ep for ep in self._endpoints.values() if ep.group == group]

    def list_groups(self) -> List[str]:
        """Return all unique group names."""
        return sorted({ep.group for ep in self._endpoints.values() if ep.group})

    def clear(self) -> None:
        """Remove all registered endpoints."""
        self._endpoints.clear()

    def __len__(self) -> int:
        return len(self._endpoints)

    def __contains__(self, name: str) -> bool:
        return name in self._endpoints

    def __iter__(self):
        return iter(self._endpoints.values())
