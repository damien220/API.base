"""URLBuilder — assembles full URLs from components."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union
from urllib.parse import quote, urlencode, urlparse, urlunparse


class URLBuilder:
    """Builds fully-qualified URLs from base URL, API version, path,
    path parameters, and query parameters.

    Handles trailing slashes, encoding, and normalization::

        url = (
            URLBuilder("https://api.example.com", api_version="v1")
            .path("/users/{user_id}/posts")
            .path_params(user_id=42)
            .query(page=1, limit=20)
            .build()
        )
        # → "https://api.example.com/v1/users/42/posts?page=1&limit=20"
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_version: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._path: str = ""
        self._path_params: Dict[str, Any] = {}
        self._query_params: Dict[str, Any] = {}

    def path(self, path: str) -> URLBuilder:
        """Set the URL path (may contain ``{param}`` placeholders)."""
        self._path = path if path.startswith("/") else f"/{path}"
        return self

    def path_params(self, **params: Any) -> URLBuilder:
        """Set path parameter values for template substitution."""
        self._path_params.update(params)
        return self

    def query(self, **params: Any) -> URLBuilder:
        """Add query parameters."""
        self._query_params.update(params)
        return self

    def query_dict(self, params: Dict[str, Any]) -> URLBuilder:
        """Add query parameters from a dictionary."""
        self._query_params.update(params)
        return self

    def build(self) -> str:
        """Assemble and return the full URL string."""
        # Base + version
        base = self._base_url
        if self._api_version:
            base = f"{base}/{self._api_version}"

        # Resolve path parameters
        resolved_path = self._path
        if self._path_params:
            try:
                resolved_path = self._path.format(**{
                    k: quote(str(v), safe="")
                    for k, v in self._path_params.items()
                })
            except KeyError as exc:
                raise KeyError(
                    f"Missing path parameter {exc} in path '{self._path}'"
                ) from exc

        # Combine base + path
        url = f"{base}{resolved_path}"

        # Append query string
        if self._query_params:
            filtered = {
                k: v for k, v in self._query_params.items() if v is not None
            }
            if filtered:
                qs = urlencode(filtered, doseq=True)
                url = f"{url}?{qs}"

        return url

    def reset(self) -> URLBuilder:
        """Clear path, path params, and query params (keep base URL)."""
        self._path = ""
        self._path_params.clear()
        self._query_params.clear()
        return self
