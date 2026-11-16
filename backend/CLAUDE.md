# Backend — Developer Guide

## Setup and tests

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest -v --cov=app
uv run --extra dev ruff check app/ tests/
```

## Market data (`app/market/`)

Design: `planning/MARKET_DATA_INTERFACE.md` and `planning/MARKET_SIMULATOR.md`. Prices are integer KRW, tick-aligned, tickers are 6-char `str` codes.

```python
from app.market import PriceCache, create_source, create_stream_router, NameRegistry, TickerTracker

cache = PriceCache()
source = create_source(cache)             # USE_YFINANCE=true -> YFinanceSource, else SimulatorSource
await source.start({"005930", "000660"})  # cache is seeded before returning
cache.price("005930")                     # int | None; trades must reject None
app.include_router(create_stream_router(cache, NameRegistry().get))  # GET /api/stream/prices
await source.stop()
```

- `PriceQuote.to_event(name)` is the exact SSE payload from PLAN section 6; `cache.changed_since(version)` drives SSE deltas (`id:` = cache version, `Last-Event-ID` resumes).
- `MarketDataSource` (base.py): `start/stop/add_ticker -> bool/remove_ticker/tickers/status`.
- `SimulatorSource.step()` is public for deterministic tests (`seed=`). Env: `SIM_SEED`, `SIM_TIME_SCALE`, `SIM_EVENT_RATE`, `SIM_UPDATE_INTERVAL`.
- `YFinanceSource` takes injectable `last_price_fn` / `batch_fn`; listing CSV is `backend/schema/krx_listing.csv` (decides `.KS` vs `.KQ`, else probes).
- `TickerTracker.sync()` keeps tracked set = watchlist ∪ positions; `price_for_trade()` raises `PriceUnavailableError`.
