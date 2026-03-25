"""Common header utilities for API requests."""

from __future__ import annotations

import platform
from typing import Any, Dict, Optional

from ..types import ContentType


def default_user_agent(
    package_name: str = "api-client-base",
    package_version: str = "0.1.0",
) -> str:
    """Build a descriptive User-Agent string.

    Format: ``{package}/{version} Python/{py_version} {os}/{os_version}``

    Args:
        package_name: Name of the client package.
        package_version: Version of the client package.

    Returns:
        User-Agent string.
    """
    py_version = platform.python_version()
    os_name = platform.system()
    os_version = platform.release()
    return f"{package_name}/{package_version} Python/{py_version} {os_name}/{os_version}"


def content_type_for_body(
    body: Any,
    files: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Infer the Content-Type header from the request body.

    Args:
        body: The request body.
        files: Multipart files dict (if present, returns multipart).

    Returns:
        Content-Type string, or None if unknown.
    """
    if files:
        return ContentType.MULTIPART.value
    if isinstance(body, dict) or isinstance(body, list):
        return ContentType.JSON.value
    if isinstance(body, str):
        return ContentType.TEXT.value
    if isinstance(body, bytes):
        return ContentType.OCTET_STREAM.value
    return None


def merge_headers(*header_dicts: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Merge multiple header dictionaries (later dicts take priority).

    Args:
        *header_dicts: Header dictionaries to merge. None values are skipped.

    Returns:
        Merged headers dictionary.
    """
    result: Dict[str, str] = {}
    for headers in header_dicts:
        if headers:
            result.update(headers)
    return result


def redact_auth_headers(
    headers: Dict[str, str],
    sensitive_names: Optional[set[str]] = None,
) -> Dict[str, str]:
    """Return a copy of headers with sensitive values redacted.

    Useful for logging — prevents API keys and tokens from
    appearing in log output.

    Args:
        headers: Original headers.
        sensitive_names: Set of header names to redact (case-insensitive).
            Defaults to Authorization, X-API-Key, Cookie, etc.

    Returns:
        Copy with sensitive values replaced by "***REDACTED***".
    """
    if sensitive_names is None:
        sensitive_names = {
            "authorization",
            "x-api-key",
            "api-key",
            "cookie",
            "set-cookie",
            "proxy-authorization",
            "x-auth-token",
        }

    redacted = {}
    for key, value in headers.items():
        if key.lower() in sensitive_names:
            # Show prefix for Bearer tokens to aid debugging
            if value.lower().startswith("bearer ") and len(value) > 15:
                redacted[key] = f"Bearer ***{value[-4:]}"
            else:
                redacted[key] = "***REDACTED***"
        else:
            redacted[key] = value
    return redacted


def parse_content_type(header_value: str) -> tuple[str, Dict[str, str]]:
    """Parse a Content-Type header into media type and parameters.

    Example::

        media_type, params = parse_content_type("application/json; charset=utf-8")
        # media_type = "application/json"
        # params = {"charset": "utf-8"}

    Args:
        header_value: The Content-Type header value.

    Returns:
        Tuple of (media_type, parameters_dict).
    """
    parts = header_value.split(";")
    media_type = parts[0].strip().lower()
    params: Dict[str, str] = {}
    for part in parts[1:]:
        part = part.strip()
        if "=" in part:
            key, _, value = part.partition("=")
            params[key.strip().lower()] = value.strip().strip('"')
    return media_type, params
