"""SSE endpoint: GET /api/stream/prices."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

KEEPALIVE_SECONDS = 15.0


async def generate_events(
    cache: PriceCache,
    name_of: Callable[[str], str],
    is_disconnected: Callable[[], Awaitable[bool]],
    since: int = 0,
    interval: float = 0.5,
    keepalive: float = KEEPALIVE_SECONDS,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: one event per changed ticker (all of them on first pass)."""
    yield "retry: 2000\n\n"
    idle = 0.0
    while not await is_disconnected():
        quotes = cache.changed_since(since)
        if quotes:
            for q in quotes:
                payload = json.dumps(q.to_event(name_of(q.ticker)), separators=(",", ":"))
                yield f"id: {q.version}\ndata: {payload}\n\n"
                since = max(since, q.version)
            idle = 0.0
        else:
            idle += interval
            if idle >= keepalive:
                yield ": keepalive\n\n"
                idle = 0.0
        await asyncio.sleep(interval)


def create_stream_router(cache: PriceCache, name_of: Callable[[str], str] | None = None) -> APIRouter:
    """Build a fresh router (safe to call more than once)."""
    router = APIRouter()
    resolve_name = name_of or (lambda t: t)

    @router.get("/api/stream/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        last_id = request.headers.get("last-event-id", "")
        since = int(last_id) if last_id.isdigit() else 0
        return StreamingResponse(
            generate_events(cache, resolve_name, request.is_disconnected, since),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router
