"""Paginator — async iterator that auto-fetches all pages from a paginated API."""

from __future__ import annotations

from typing import Any, AsyncIterator, Callable, Awaitable, Dict, List, Optional

from .strategies import PageInfo, PaginationStrategy
from ..request.models import APIResponse


# Type for the function that fetches a single page
PageFetcher = Callable[..., Awaitable[APIResponse]]


class Paginator:
    """Async iterator that transparently follows pagination.

    Fetches pages one at a time using the provided ``fetch_page``
    callable and extracts items using the pagination strategy.
    Yields individual items across all pages.

    Usage::

        paginator = Paginator(
            fetch_page=lambda **params: client.get("/users", params=params),
            strategy=CursorPagination(cursor_param="after", items_path="data"),
        )

        async for user in paginator:
            print(user["name"])

        # Or collect all items
        all_users = await paginator.collect()

    Args:
        fetch_page: Async callable that accepts keyword params and returns
            an APIResponse. The paginator will pass next-page params to it.
        strategy: The pagination strategy to use.
        initial_params: Initial query parameters for the first page.
        max_pages: Maximum number of pages to fetch. None = no limit.
        max_items: Maximum total items to yield. None = no limit.
    """

    def __init__(
        self,
        fetch_page: PageFetcher,
        strategy: PaginationStrategy,
        *,
        initial_params: Optional[Dict[str, Any]] = None,
        max_pages: Optional[int] = None,
        max_items: Optional[int] = None,
    ) -> None:
        self._fetch_page = fetch_page
        self._strategy = strategy
        self._initial_params = initial_params or {}
        self._max_pages = max_pages
        self._max_items = max_items

    async def __aiter__(self) -> AsyncIterator[Any]:
        """Yield individual items across all pages."""
        current_params = dict(self._initial_params)
        pages_fetched = 0
        items_yielded = 0

        while True:
            # Check page limit
            if self._max_pages is not None and pages_fetched >= self._max_pages:
                return

            # Fetch one page
            response = await self._fetch_page(**current_params)
            pages_fetched += 1

            # Extract items from this page
            items = self._strategy.extract_items(response.body)

            for item in items:
                yield item
                items_yielded += 1
                if self._max_items is not None and items_yielded >= self._max_items:
                    return

            # Determine next page
            page_info = self._strategy.extract_page_info(
                response.body, response.headers, current_params
            )

            if not page_info.has_next:
                return

            # Build params for next request
            if page_info.next_url:
                # For Link header pagination, the URL contains everything
                current_params = {"_override_url": page_info.next_url}
            else:
                current_params = {**current_params, **page_info.next_params}

    async def collect(self) -> List[Any]:
        """Fetch all pages and return all items as a single list."""
        items: List[Any] = []
        async for item in self:
            items.append(item)
        return items

    async def pages(self) -> AsyncIterator[List[Any]]:
        """Yield one list of items per page (instead of individual items).

        Useful when you need to process items page-by-page rather than
        as a flat stream.
        """
        current_params = dict(self._initial_params)
        pages_fetched = 0

        while True:
            if self._max_pages is not None and pages_fetched >= self._max_pages:
                return

            response = await self._fetch_page(**current_params)
            pages_fetched += 1

            items = self._strategy.extract_items(response.body)
            yield items

            page_info = self._strategy.extract_page_info(
                response.body, response.headers, current_params
            )

            if not page_info.has_next:
                return

            if page_info.next_url:
                current_params = {"_override_url": page_info.next_url}
            else:
                current_params = {**current_params, **page_info.next_params}

    async def first_page(self) -> List[Any]:
        """Fetch only the first page and return its items."""
        response = await self._fetch_page(**self._initial_params)
        return self._strategy.extract_items(response.body)
