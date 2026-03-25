"""APIRequest and APIResponse dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class APIRequest:
    """Represents an outgoing API request."""

    method: str
    url: str
    headers: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    body: Any = None
    files: Optional[Dict[str, Any]] = None
    timeout: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_body(self) -> bool:
        return self.body is not None

    @property
    def has_files(self) -> bool:
        return self.files is not None and len(self.files) > 0


@dataclass
class APIResponse:
    """Represents a parsed API response."""

    status_code: int
    headers: Dict[str, str]
    body: Any
    raw_response: Any = None
    elapsed_ms: float = 0.0
    request: Optional[APIRequest] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_success(self) -> bool:
        return 200 <= self.status_code < 300

    @property
    def is_client_error(self) -> bool:
        return 400 <= self.status_code < 500

    @property
    def is_server_error(self) -> bool:
        return 500 <= self.status_code < 600
