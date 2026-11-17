"""SSE endpoint: GET /api/stream/prices.

Protocol (planning/MARKET_DATA_INTERFACE.md §7)::

    retry: 2000

    id: 1542
    data: {"ticker":"005930","name":"Samsung Electronics","price":75400,...}

    : keepalive

- One event per ticker, in the exact PLAN §6 payload shape.
- ``id`` is the cache version. On connect every tracked ticker is sent (initial
  snapshot); after that only tickers whose quote changed.
- Reconnecting browsers send ``Last-Event-ID``; we resume from that version.
  Quotes are latest-value data, so a version newer than the cache (server
  restart) simply yields a fresh full snapshot.
- A ``: keepalive`` comment is sent after ``keepalive`` seconds without data
  (yfinance can be silent for minutes, and proxies drop idle connections).
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache
from .names import NameRegistry

logger = logging.getLogger(__name__)

RETRY_MS = 2000

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",  # disable nginx buffering if proxied
}


def parse_last_event_id(value: str | None, current_version: int) -> int:
    """Starting version for a (re)connecting client. Unknown/future ids → 0 (full snapshot)."""
    if value and value.strip().isdigit():
        since = int(value.strip())
        if since <= current_version:
            return since
    return 0


def format_event(version: int, payload: dict) -> str:
    return (
        f"id: {version}\ndata: {json.dumps(payload, separators=(',', ':'), ensure_ascii=False)}\n\n"
    )


async def price_events(
    cache: PriceCache,
    names: NameRegistry,
    is_disconnected: Callable[[], Awaitable[bool]],
    since: int = 0,
    interval: float = 0.5,
    keepalive: float = 15.0,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames until ``is_disconnected()`` returns True."""
    yield f"retry: {RETRY_MS}\n\n"
    idle = 0.0
    while not await is_disconnected():
        quotes = cache.changed_since(since)
        if quotes:
            for quote in quotes:
                yield format_event(quote.version, quote.to_event(names.get(quote.ticker)))
                since = max(since, quote.version)
            idle = 0.0
        else:
            idle += interval
            if idle >= keepalive:
                yield ": keepalive\n\n"
                idle = 0.0
        await asyncio.sleep(interval)


def create_stream_router(
    cache: PriceCache,
    names: NameRegistry | None = None,
    interval: float = 0.5,
    keepalive: float = 15.0,
) -> APIRouter:
    """Build a fresh router (safe to call more than once, e.g. in tests)."""
    registry = names or NameRegistry()
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        since = parse_last_event_id(request.headers.get("last-event-id"), cache.version)
        client = request.client.host if request.client else "unknown"
        logger.info("SSE client connected: %s (since=%d)", client, since)
        return StreamingResponse(
            price_events(cache, registry, request.is_disconnected, since, interval, keepalive),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return router
