"""Stream parsers for SSE (Server-Sent Events) and NDJSON responses."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Optional


@dataclass
class SSEEvent:
    """Represents a single Server-Sent Event.

    Attributes:
        data: The event payload (string or parsed JSON).
        event: Event type (default: "message").
        id: Event ID for resuming.
        retry: Reconnection time in milliseconds.
    """

    data: Any = None
    event: str = "message"
    id: Optional[str] = None
    retry: Optional[int] = None

    @property
    def is_done(self) -> bool:
        """Check if this is a terminal event (``[DONE]`` marker)."""
        return self.data == "[DONE]"

    @property
    def json_data(self) -> Any:
        """Parse data as JSON. Returns None if not valid JSON."""
        if isinstance(self.data, str):
            try:
                return json.loads(self.data)
            except (json.JSONDecodeError, ValueError):
                return None
        return self.data


async def parse_sse(
    chunks: AsyncIterator[bytes],
    *,
    parse_json: bool = True,
) -> AsyncIterator[SSEEvent]:
    """Parse a stream of bytes into SSE events.

    Follows the Server-Sent Events specification (W3C). Handles
    multi-line data fields, event types, IDs, and retry values.

    Usage::

        async for event in parse_sse(client.stream("GET", "/events")):
            if event.is_done:
                break
            print(event.data)

    Args:
        chunks: Async iterator of raw bytes (from ``client.stream()``).
        parse_json: If True, attempt to parse each event's data as JSON.

    Yields:
        SSEEvent instances.
    """
    buffer = ""

    async for chunk in chunks:
        buffer += chunk.decode("utf-8", errors="replace")

        # SSE events are separated by double newlines
        while "\n\n" in buffer:
            event_text, buffer = buffer.split("\n\n", 1)
            event = _parse_sse_event(event_text, parse_json=parse_json)
            if event is not None:
                yield event

    # Handle remaining buffer (if stream ends without trailing \n\n)
    if buffer.strip():
        event = _parse_sse_event(buffer, parse_json=parse_json)
        if event is not None:
            yield event


async def parse_ndjson(
    chunks: AsyncIterator[bytes],
) -> AsyncIterator[Any]:
    """Parse a stream of Newline-Delimited JSON (NDJSON).

    Each line is a complete JSON object. Commonly used by APIs
    for streaming large result sets.

    Usage::

        async for obj in parse_ndjson(client.stream("GET", "/export")):
            print(obj)

    Args:
        chunks: Async iterator of raw bytes.

    Yields:
        Parsed JSON objects (dicts, lists, etc.).
    """
    buffer = ""

    async for chunk in chunks:
        buffer += chunk.decode("utf-8", errors="replace")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue  # Skip malformed lines

    # Handle remaining buffer
    remaining = buffer.strip()
    if remaining:
        try:
            yield json.loads(remaining)
        except json.JSONDecodeError:
            pass


async def parse_text_lines(
    chunks: AsyncIterator[bytes],
    *,
    encoding: str = "utf-8",
) -> AsyncIterator[str]:
    """Parse a stream of bytes into text lines.

    A simpler alternative when the stream format is plain text
    with newline-delimited records.

    Args:
        chunks: Async iterator of raw bytes.
        encoding: Character encoding.

    Yields:
        Non-empty text lines.
    """
    buffer = ""

    async for chunk in chunks:
        buffer += chunk.decode(encoding, errors="replace")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if line:
                yield line

    remaining = buffer.strip()
    if remaining:
        yield remaining


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_sse_event(text: str, *, parse_json: bool = True) -> Optional[SSEEvent]:
    """Parse a single SSE event block into an SSEEvent."""
    data_lines: list[str] = []
    event_type = "message"
    event_id: Optional[str] = None
    retry: Optional[int] = None

    for line in text.split("\n"):
        line = line.strip()

        if not line or line.startswith(":"):
            # Comment or empty line
            continue

        if ":" in line:
            field, _, value = line.partition(":")
            value = value.lstrip(" ")  # SSE spec: strip single leading space
        else:
            field = line
            value = ""

        if field == "data":
            data_lines.append(value)
        elif field == "event":
            event_type = value
        elif field == "id":
            event_id = value
        elif field == "retry":
            try:
                retry = int(value)
            except ValueError:
                pass

    if not data_lines and event_id is None and event_type == "message":
        return None  # Empty event

    data: Any = "\n".join(data_lines) if data_lines else None

    # Attempt JSON parse
    if parse_json and isinstance(data, str) and data != "[DONE]":
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            pass  # Keep as string

    return SSEEvent(data=data, event=event_type, id=event_id, retry=retry)
