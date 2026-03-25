"""Serialization helpers for API request/response bodies."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Optional, Union
from urllib.parse import urlencode


def serialize_json(data: Any, *, sort_keys: bool = False) -> str:
    """Serialize data to a JSON string.

    Args:
        data: JSON-serializable data.
        sort_keys: Whether to sort dictionary keys.

    Returns:
        JSON string.
    """
    return json.dumps(data, sort_keys=sort_keys, default=str)


def deserialize_json(text: str) -> Any:
    """Deserialize a JSON string to Python objects.

    Args:
        text: JSON string.

    Returns:
        Parsed Python object.

    Raises:
        ValueError: If the string is not valid JSON.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON: {exc}") from exc


def serialize_form(data: Dict[str, Any]) -> str:
    """Serialize data to URL-encoded form format.

    Args:
        data: Dictionary of form fields.

    Returns:
        URL-encoded string.
    """
    return urlencode(
        {k: v for k, v in data.items() if v is not None},
        doseq=True,
    )


def body_hash(
    body: Any,
    *,
    algorithm: str = "sha256",
) -> str:
    """Generate a deterministic hash of a request body.

    Used for cache key generation. Handles JSON-serializable data,
    strings, and bytes.

    Args:
        body: The request body to hash.
        algorithm: Hash algorithm name (default: sha256).

    Returns:
        Hex digest string.
    """
    h = hashlib.new(algorithm)

    if body is None:
        h.update(b"__none__")
    elif isinstance(body, bytes):
        h.update(body)
    elif isinstance(body, str):
        h.update(body.encode("utf-8"))
    else:
        # JSON-serializable — sort keys for determinism
        h.update(json.dumps(body, sort_keys=True, default=str).encode("utf-8"))

    return h.hexdigest()


def build_cache_key(
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    body: Any = None,
) -> str:
    """Build a deterministic cache key from request components.

    Key format: ``{method}:{url}:{params_hash}:{body_hash}``

    Args:
        method: HTTP method.
        url: Full request URL.
        params: Query parameters.
        body: Request body.

    Returns:
        Cache key string.
    """
    parts = [method.upper(), url]

    if params:
        sorted_params = sorted(params.items())
        params_str = urlencode(sorted_params, doseq=True)
        parts.append(hashlib.sha256(params_str.encode()).hexdigest()[:16])
    else:
        parts.append("_")

    if body is not None:
        parts.append(body_hash(body)[:16])
    else:
        parts.append("_")

    return ":".join(parts)


def safe_json_parse(
    text: Union[str, bytes],
    default: Any = None,
) -> Any:
    """Parse JSON without raising exceptions.

    Args:
        text: JSON string or bytes.
        default: Value to return if parsing fails.

    Returns:
        Parsed object or default.
    """
    try:
        if isinstance(text, bytes):
            text = text.decode("utf-8")
        return json.loads(text)
    except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return default
