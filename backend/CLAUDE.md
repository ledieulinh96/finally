# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
uv run uvicorn app.main:app --port 8000 --workers 1   # ALWAYS one worker (in-process price cache)
# Handy dev/test env: DB_PATH=/tmp/x.db LLM_MOCK=true SIM_SEED=42 STATIC_DIR=../frontend/out
```

## Market Data API (KRX: KOSPI / KOSDAQ)

The market data subsystem lives in `app/market/`. The summary is in `planning/MARKET_DATA_SUMMARY.md`. Use these imports:

```python
from app.market import (
    PriceCache, PriceQuote, MarketDataSource, NameRegistry, TickerTracker,
    MarketSettings, create_market_data_source, create_stream_router,
    normalize_ticker, snap_to_tick, market_session, DEFAULT_TICKERS,
)
```

### Core types

- **`PriceQuote`**: an immutable quote.
  - Fields: `ticker` (str, e.g. `"005930"`); `price`, `prev_price` and `session_open` (all `int` KRW); `timestamp` (UTC datetime); `version`.
  - Properties: `direction`, `change`, `session_change_pct`.
  - `to_event(name)` returns the exact SSE payload from PLAN §6.
- **`PriceCache`**: thread-safe and versioned.
  - `update(ticker, price: int)`: a non-int or non-positive price raises.
  - `get`, `price` (returns `int | None`), `get_all`, `changed_since(version)`, `remove`, `version`.
- **`MarketDataSource`** has two implementations: `SimulatorSource` (the default) and `YFinanceSource` (`USE_YFINANCE=true`). Its methods:
  - `start(tickers)` and `stop()`;
  - `add_ticker(t) -> bool`, which returns False when the ticker is unknown;
  - `remove_ticker(t)`;
  - `tickers`, `status` (`ok` / `degraded` / `stopped`) and `name`.
- **`TickerTracker.sync(watchlist, positions)`**: call it after every watchlist change and after any trade that opens or closes a position. The tracked set must stay watchlist ∪ positions.
- **`NameRegistry`**: maps ticker → English name. It is seeded from `schema/krx_listing.csv` and the defaults, and falls back to the ticker code.

### Rules for consumers

- Tickers are always 6-character strings. Validate them with `normalize_ticker()`.
- Trades fill at `cache.price(t)`. If that is `None`, call `tracker.ensure(t)` first, then reject with "No price available". Never fill at 0.
- Sources never touch the DB. The API layer owns persistence.

### SSE

`create_stream_router(cache, names)` serves `GET /api/stream/prices`:
- one event per ticker, with `id:` set to the cache version;
- a full snapshot on connect, deltas after that;
- `Last-Event-ID` resume and 15 s keepalives.

## Application layout (beyond `app/market/`)

| Module | Owner | Purpose |
|---|---|---|
| `app/main.py` | backend | `create_app(market_settings=None, app_settings=None)`; lifespan: `db.init_db` → load names → start source with watchlist ∪ positions → 60 s snapshot task. Static catch-all registered last. |
| `app/config.py` | backend | Loads `<repo>/.env` (`override=False`); `Settings.from_env()` → `db_path` (`DB_PATH`), `static_dir` (`STATIC_DIR`, default `backend/static`), `llm_mock`, API keys. |
| `app/services/` | backend | `PortfolioService` (on `app.state.services`) — trades, watchlist, valuation, history, snapshots, tracker re-sync. Typed `ServiceError`s carry `status_code`. Contract: `planning/SERVICES_INTERFACE.md`. |
| `app/api/routes.py` | backend | All PLAN §8 REST routes; `POST /api/chat` → `app.llm.handle_chat`. |
| `app/api/stream.py` | backend | Mounts `GET /api/stream/prices`, reusing `app.market.stream.price_events` unchanged, but the stream also ends when `app.state.shutdown` is set. |
| `app/api/shutdown.py` | backend | `ShutdownFlag` + `install_signal_hooks`: the lifespan chains a SIGINT/SIGTERM handler in front of uvicorn's, so open SSE streams close immediately and `docker stop` exits in under 1 s (uvicorn otherwise waits forever for them). |
| `app/api/static.py` | backend | Serves the Next.js export with SPA fallback; unknown `/api/*` stays a JSON 404. Skipped if `STATIC_DIR/index.html` is missing. |
| `app/db/` | database | SQLite repository (`planning/DB_INTERFACE.md`). |
| `app/llm/` | llm | Chat flow (`planning/LLM_INTERFACE.md`). |

Graceful shutdown: uvicorn waits for open connections to drain *before* running lifespan shutdown and never tells a streaming response it is stopping, so an open EventSource would block SIGTERM forever. `app/api/shutdown.py` sets the flag from a chained signal handler (not the lifespan `finally`), which ends SSE streams at once. The Docker CMD's `--timeout-graceful-shutdown 3` is only a safety net for any other long-lived request.

Rules: routes never touch `app.db` directly — go through `PortfolioService` so REST and chat share validation.

Tests for the app layer live in `tests/api/` and `tests/services/`; their `conftest.py` builds the app on a tmp `DB_PATH` with `LLM_MOCK=true` and a seeded simulator.

## Running Tests

```bash
uv run --extra dev pytest -v              # All tests
uv run --extra dev pytest --cov=app       # With coverage
uv run --extra dev ruff check app/ tests/ # Lint
uv run --extra dev ruff format app/ tests/
```

In the Claude Code sandbox, prefix commands with `UV_CACHE_DIR="$TMPDIR/uv-cache"`, because the global uv cache is not writable there.

## Demo

```bash
uv run market_data_demo.py   # Live terminal dashboard with simulated KOSPI prices
```
