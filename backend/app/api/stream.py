"""``GET /api/stream/prices`` — wraps the market SSE generator so it ends on shutdown.

Same protocol and payloads as ``app.market.stream`` (whose ``price_events`` is
reused unchanged); the only difference is that the stream also stops when the
app's ``ShutdownFlag`` is set, so open EventSource connections don't block a
graceful SIGTERM. Browsers simply reconnect (``retry: 2000``) to the new server.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..market import NameRegistry, PriceCache
from ..market.stream import SSE_HEADERS, parse_last_event_id, price_events
from .shutdown import ShutdownFlag

logger = logging.getLogger(__name__)


def create_stream_router(
    cache: PriceCache,
    names: NameRegistry,
    shutdown: ShutdownFlag,
    interval: float = 0.5,
    keepalive: float = 15.0,
) -> APIRouter:
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        since = parse_last_event_id(request.headers.get("last-event-id"), cache.version)

        async def stop() -> bool:
            return shutdown.is_set() or await request.is_disconnected()

        return StreamingResponse(
            price_events(cache, names, stop, since, interval, keepalive),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )

    return router
