"""Pagination strategies for extracting next-page info from API responses."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class PageInfo:
    """Describes how to fetch the next page.

    The paginator uses this to decide whether to continue and how
    to build the next request.
    """

    has_next: bool
    next_params: Dict[str, Any]
    """Query params / body fields to set on the next request."""
    next_url: Optional[str] = None
    """If set, override the entire URL for the next request."""
    total: Optional[int] = None
    """Total number of items, if the API reports it."""
    current_page: Optional[int] = None


class PaginationStrategy(ABC):
    """Abstract base for extracting pagination info from a response.

    Concrete strategies inspect the response body and/or headers to
    determine whether there is a next page and what parameters to
    send to fetch it.
    """

    @abstractmethod
    def extract_page_info(
        self,
        response_body: Any,
        response_headers: Dict[str, str],
        current_params: Dict[str, Any],
    ) -> PageInfo:
        """Examine a response and return next-page information.

        Args:
            response_body: The parsed response body.
            response_headers: Response headers dict.
            current_params: Query params used for the current request.

        Returns:
            PageInfo describing how (or whether) to fetch the next page.
        """

    @abstractmethod
    def extract_items(self, response_body: Any) -> list[Any]:
        """Extract the list of items from a single page response.

        Args:
            response_body: The parsed response body.

        Returns:
            List of items from this page.
        """


class CursorPagination(PaginationStrategy):
    """Cursor-based pagination (e.g., OpenAI, Slack, Stripe).

    Many modern APIs return a cursor/token in the response that must
    be passed as a query parameter to fetch the next page.

    Args:
        cursor_param: Query param name to send the cursor (default: "after").
        cursor_path: Dot-separated path to the cursor in the response body
            (default: "next_cursor"). Supports nested paths like "meta.next_cursor".
        items_path: Dot-separated path to the items list in the response body
            (default: "data").
        has_more_path: Dot-separated path to a boolean indicating more pages
            (default: "has_more"). If None, presence of a non-empty cursor is used.
    """

    def __init__(
        self,
        *,
        cursor_param: str = "after",
        cursor_path: str = "next_cursor",
        items_path: str = "data",
        has_more_path: Optional[str] = "has_more",
    ) -> None:
        self._cursor_param = cursor_param
        self._cursor_path = cursor_path
        self._items_path = items_path
        self._has_more_path = has_more_path

    def extract_page_info(
        self,
        response_body: Any,
        response_headers: Dict[str, str],
        current_params: Dict[str, Any],
    ) -> PageInfo:
        cursor = _get_nested(response_body, self._cursor_path)

        if self._has_more_path is not None:
            has_more = bool(_get_nested(response_body, self._has_more_path))
        else:
            has_more = cursor is not None and cursor != ""

        if has_more and cursor:
            return PageInfo(
                has_next=True,
                next_params={self._cursor_param: cursor},
            )
        return PageInfo(has_next=False, next_params={})

    def extract_items(self, response_body: Any) -> list[Any]:
        items = _get_nested(response_body, self._items_path)
        if isinstance(items, list):
            return items
        if items is None:
            return []
        return [items]


class OffsetPagination(PaginationStrategy):
    """Offset/limit pagination (e.g., many SQL-backed APIs).

    Uses ``offset`` and ``limit`` query parameters. The next page
    is calculated by incrementing offset by the page size.

    Args:
        offset_param: Query param name for the offset (default: "offset").
        limit_param: Query param name for the page size (default: "limit").
        default_limit: Default page size if not set in params (default: 20).
        items_path: Dot-separated path to the items list (default: "data").
        total_path: Dot-separated path to total count (default: "total").
            If None, pagination stops when a page returns fewer items than limit.
    """

    def __init__(
        self,
        *,
        offset_param: str = "offset",
        limit_param: str = "limit",
        default_limit: int = 20,
        items_path: str = "data",
        total_path: Optional[str] = "total",
    ) -> None:
        self._offset_param = offset_param
        self._limit_param = limit_param
        self._default_limit = default_limit
        self._items_path = items_path
        self._total_path = total_path

    def extract_page_info(
        self,
        response_body: Any,
        response_headers: Dict[str, str],
        current_params: Dict[str, Any],
    ) -> PageInfo:
        offset = int(current_params.get(self._offset_param, 0))
        limit = int(current_params.get(self._limit_param, self._default_limit))
        items = self.extract_items(response_body)
        next_offset = offset + limit

        if self._total_path is not None:
            total = _get_nested(response_body, self._total_path)
            if total is not None:
                total = int(total)
                has_next = next_offset < total
                return PageInfo(
                    has_next=has_next,
                    next_params={
                        self._offset_param: next_offset,
                        self._limit_param: limit,
                    },
                    total=total,
                )

        # Fallback: stop if page returned fewer items than limit
        has_next = len(items) >= limit
        return PageInfo(
            has_next=has_next,
            next_params={
                self._offset_param: next_offset,
                self._limit_param: limit,
            },
        )

    def extract_items(self, response_body: Any) -> list[Any]:
        items = _get_nested(response_body, self._items_path)
        if isinstance(items, list):
            return items
        if items is None:
            return []
        return [items]


class PageNumberPagination(PaginationStrategy):
    """Page-number pagination (e.g., ``?page=2&per_page=25``).

    Args:
        page_param: Query param name for the page number (default: "page").
        per_page_param: Query param name for page size (default: "per_page").
        default_per_page: Default page size (default: 20).
        items_path: Dot-separated path to items list (default: "data").
        total_pages_path: Path to total pages count (default: "total_pages").
        total_items_path: Path to total items count (default: None).
    """

    def __init__(
        self,
        *,
        page_param: str = "page",
        per_page_param: str = "per_page",
        default_per_page: int = 20,
        items_path: str = "data",
        total_pages_path: Optional[str] = "total_pages",
        total_items_path: Optional[str] = None,
    ) -> None:
        self._page_param = page_param
        self._per_page_param = per_page_param
        self._default_per_page = default_per_page
        self._items_path = items_path
        self._total_pages_path = total_pages_path
        self._total_items_path = total_items_path

    def extract_page_info(
        self,
        response_body: Any,
        response_headers: Dict[str, str],
        current_params: Dict[str, Any],
    ) -> PageInfo:
        current_page = int(current_params.get(self._page_param, 1))
        per_page = int(
            current_params.get(self._per_page_param, self._default_per_page)
        )
        items = self.extract_items(response_body)
        next_page = current_page + 1

        total = None
        if self._total_items_path:
            total = _get_nested(response_body, self._total_items_path)
            if total is not None:
                total = int(total)

        # Determine has_next
        if self._total_pages_path:
            total_pages = _get_nested(response_body, self._total_pages_path)
            if total_pages is not None:
                has_next = next_page <= int(total_pages)
                return PageInfo(
                    has_next=has_next,
                    next_params={
                        self._page_param: next_page,
                        self._per_page_param: per_page,
                    },
                    total=total,
                    current_page=current_page,
                )

        # Fallback: stop when fewer items than per_page
        has_next = len(items) >= per_page
        return PageInfo(
            has_next=has_next,
            next_params={
                self._page_param: next_page,
                self._per_page_param: per_page,
            },
            total=total,
            current_page=current_page,
        )

    def extract_items(self, response_body: Any) -> list[Any]:
        items = _get_nested(response_body, self._items_path)
        if isinstance(items, list):
            return items
        if items is None:
            return []
        return [items]


class LinkHeaderPagination(PaginationStrategy):
    """Link-header pagination (RFC 8288, used by GitHub, GitLab).

    Parses the ``Link`` response header to find the ``rel="next"`` URL.

    Args:
        items_path: Dot-separated path to items list (default: root list).
            If None, the response body is expected to be a list directly.
    """

    def __init__(
        self,
        *,
        items_path: Optional[str] = None,
    ) -> None:
        self._items_path = items_path

    def extract_page_info(
        self,
        response_body: Any,
        response_headers: Dict[str, str],
        current_params: Dict[str, Any],
    ) -> PageInfo:
        next_url = self._parse_link_header(response_headers)
        if next_url:
            return PageInfo(has_next=True, next_params={}, next_url=next_url)
        return PageInfo(has_next=False, next_params={})

    def extract_items(self, response_body: Any) -> list[Any]:
        if self._items_path is None:
            return response_body if isinstance(response_body, list) else [response_body]
        items = _get_nested(response_body, self._items_path)
        if isinstance(items, list):
            return items
        if items is None:
            return []
        return [items]

    @staticmethod
    def _parse_link_header(headers: Dict[str, str]) -> Optional[str]:
        """Extract the 'next' URL from a Link header."""
        link_value = None
        for key, val in headers.items():
            if key.lower() == "link":
                link_value = val
                break
        if not link_value:
            return None

        for part in link_value.split(","):
            part = part.strip()
            match = re.match(r'<([^>]+)>;\s*rel="next"', part)
            if match:
                return match.group(1)
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_nested(data: Any, path: str) -> Any:
    """Get a value from a nested dict using a dot-separated path.

    Example: ``_get_nested({"meta": {"cursor": "abc"}}, "meta.cursor")`` → ``"abc"``
    """
    if data is None or not path:
        return data
    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            current = current[idx] if idx < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current
