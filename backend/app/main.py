"""FastAPI application entry point.

Wires market data (price source, SSE stream), the SQLite database, the
PortfolioService, REST routes, chat, health and static-file serving.

Run with a SINGLE worker — the price cache and simulator live in-process::

    uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import db
from .api import create_api_router, mount_static
from .api.shutdown import ShutdownFlag, install_signal_hooks
from .api.stream import create_stream_router
from .config import Settings
from .market import (
    MarketSettings,
    NameRegistry,
    PriceCache,
    TickerTracker,
    create_market_data_source,
    market_session,
)
from .services import PortfolioService

logger = logging.getLogger(__name__)


def create_app(
    settings: MarketSettings | None = None,
    app_settings: Settings | None = None,
) -> FastAPI:
    settings = settings or MarketSettings.from_env()
    app_settings = app_settings or Settings.from_env()
    cache = PriceCache()
    names = NameRegistry()
    source = create_market_data_source(cache, settings, names)
    tracker = TickerTracker(source)
    shutdown = ShutdownFlag()
    services = PortfolioService(cache, names, tracker, source, db_path=app_settings.db_path)
    try:  # optional OpenDART corp_name_eng lookup (returns None without a key)
        from .llm.dart import resolve_name

        services.add_name_resolver(resolve_name)
    except ImportError:  # pragma: no cover
        logger.warning("OpenDART name resolver unavailable")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Runs inside uvicorn's capture_signals, so this chains in front of its
        # handle_exit: SSE streams end as soon as SIGTERM/SIGINT arrives.
        restore_signals = install_signal_hooks(shutdown)
        await asyncio.to_thread(db.init_db, app_settings.db_path)
        await services.load_names()
        watch, held = await services.tracked_wanted()
        await source.start({*watch, *held})
        await services.snapshot_if_due(app_settings.snapshot_interval)
        snapshot_task = asyncio.create_task(
            services.run_snapshots(app_settings.snapshot_interval), name="portfolio-snapshots"
        )
        try:
            yield
        finally:
            shutdown.set()
            restore_signals()
            snapshot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await snapshot_task
            await source.stop()

    app = FastAPI(title="FinAlly", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.price_cache = cache
    app.state.market_source = source
    app.state.names = names
    app.state.tracker = tracker
    app.state.services = services
    app.state.shutdown = shutdown

    app.include_router(create_stream_router(cache, names, shutdown))
    app.include_router(create_api_router())

    @app.get("/api/health")
    async def health() -> dict:
        return {
            "status": "ok",
            "market_data": source.status,
            "source": source.name,
            "tickers": len(source.tickers),
            "market_session": market_session(),
        }

    # Must come last: catch-all GET for the static Next.js export.
    if not mount_static(app, app_settings.static_dir):
        logger.info("No static frontend at %s; serving API only", app_settings.static_dir)

    return app


app = create_app()
