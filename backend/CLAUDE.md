# Backend — Developer Guide

## Project Setup

```bash
cd backend
uv sync --extra dev   # Install all dependencies including test/lint tools
uv run uvicorn app.main:app --port 8000 --workers 1   # ALWAYS one worker (in-process price cache)
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
