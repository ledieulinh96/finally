"""FastAPI application entry point.

Currently wires the market data subsystem (price source, SSE stream, health).
Portfolio, watchlist, chat and static-file serving are added by later agents.

Run with a SINGLE worker — the price cache and simulator live in-process::

    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .market import (
    DEFAULT_TICKERS,
    MarketSettings,
    NameRegistry,
    PriceCache,
    TickerTracker,
    create_market_data_source,
    create_stream_router,
    market_session,
)

logger = logging.getLogger(__name__)


def create_app(settings: MarketSettings | None = None) -> FastAPI:
    settings = settings or MarketSettings.from_env()
    cache = PriceCache()
    names = NameRegistry()
    source = create_market_data_source(cache, settings, names)
    tracker = TickerTracker(source)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # TODO(backend agent): load watchlist ∪ positions from the database.
        await source.start(DEFAULT_TICKERS)
        try:
            yield
        finally:
            await source.stop()

    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.state.price_cache = cache
    app.state.market_source = source
    app.state.names = names
    app.state.tracker = tracker
    app.include_router(create_stream_router(cache, names))

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "market_data": source.status,
            "source": source.name,
            "tickers": len(source.tickers),
            "market_session": market_session(),
        }

    return app


app = create_app()
