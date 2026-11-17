# Market Data Backend — Summary

**Status:** Implemented for KOSPI/KOSDAQ (integer KRW) in `backend/app/market/`; 90 unit tests passing, ruff clean, 95% coverage.

Design sources: `MARKET_DATA_INTERFACE.md` (interface, cache, SSE, tracker), `MARKET_SIMULATOR.md` (model), `MARKET_DATA_SOURCES.md` (yfinance, listing).
`MARKET_DATA_DESIGN.md` and `planning/archive/*` describe the earlier US-stock/Massive build and are **obsolete**.

| Module | Purpose |
|---|---|
| `models.py` | `PriceQuote` (frozen) + `to_event()` = PLAN SSE payload |
| `cache.py` | `PriceCache`: thread-safe, int-only prices, version counter, `changed_since()` |
| `base.py` | `MarketDataSource` ABC (`start/stop/add_ticker->bool/remove_ticker/tickers/status`) |
| `ticks.py` | KRX tick table, `snap_to_tick/snap_down/snap_up` |
| `seed.py` | 10 seed tickers, GBM/factor params, ticker validation (`^[0-9A-Z]{6}$`), deterministic prices for unknown tickers |
| `simulator.py` | `SimulatorSource`: GBM + market/sector factors + OU mean reversion + jumps + ±30% band |
| `yfinance_source.py` | `YFinanceSource`: batch polling, `.KS`/`.KQ` mapping, backoff, degraded status |
| `listing.py` | bundled `backend/schema/krx_listing.csv`, `NameRegistry` |
| `factory.py` | `create_source()` from `USE_YFINANCE` / `SIM_*` env |
| `stream.py` | SSE `GET /api/stream/prices`: per-ticker events, `id:`/`Last-Event-ID`, keepalive |
| `tracker.py` | `TickerTracker`: tracked = watchlist ∪ positions; `price_for_trade()` |

Not done (belongs to the rest of the platform): FastAPI `main.py`/lifespan wiring, DB-backed watchlist/positions callables, OpenDART name lookup.
