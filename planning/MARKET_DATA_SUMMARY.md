# Market Data Backend — Summary

**Status:** Complete for KRX (KOSPI/KOSDAQ). Tested: 147 tests passing, 98% line coverage, ruff clean.
**Date:** 2026-11-17 · Designs: [`MARKET_DATA_INTERFACE.md`](MARKET_DATA_INTERFACE.md), [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md), [`MARKET_DATA_SOURCES.md`](MARKET_DATA_SOURCES.md)

The earlier US-market version (Massive/Polygon, AAPL…) is superseded. Its design docs remain in `planning/archive/` for history only.

## Architecture

```
MarketDataSource (ABC, base.py)
├── SimulatorSource   default — factor-model GBM + jumps + mean reversion, KRX ticks, ±30% band
└── YFinanceSource    USE_YFINANCE=true — batched ~20-min-delayed Yahoo quotes, back-off
        │  cache.update(ticker, int_price)   (only when the price changed)
        ▼
PriceCache (thread-safe, versioned; PriceQuote has price/prev_price/session_open as int KRW)
        ├──→ SSE  GET /api/stream/prices   (snapshot on connect → per-ticker deltas, id = version)
        ├──→ REST (watchlist, portfolio)    ← to be built
        └──→ trade execution                ← to be built
```

## Modules (`backend/app/market/`)

| File | Purpose |
|---|---|
| `models.py` | `PriceQuote` (frozen): `ticker, price, prev_price, session_open, timestamp, version`; `direction`, `change`, `session_change_pct`, `to_event(name)` = PLAN §6 payload |
| `cache.py` | `PriceCache`: `update` (int > 0 only), `get`, `price`, `get_all`, `changed_since(version)`, `remove`, `version` |
| `base.py` | `MarketDataSource` ABC: `start(tickers)`, `stop()`, `add_ticker() -> bool`, `remove_ticker()`, `tickers`, `status`, `name` |
| `simulator.py` | `SimulatorSource`, with a public synchronous `step()` for tests and `events` / `event_count` for jump events |
| `yfinance_source.py` | `YFinanceSource` + `YahooFetcher`. All network calls go through a `QuoteFetcher` protocol, so tests inject a fake |
| `ticks.py` | KRX tick table, `snap_to_tick`, `limit_band`, `normalize_ticker` (`^[0-9A-Z]{6}$`, strips `.KS/.KQ`) |
| `seed_data.py` | Default 10 KOSPI tickers: names, seed prices, sector, σ, β_m, β_s |
| `listing.py` | Loads `backend/schema/krx_listing.csv` (65 large caps: English name + KOSPI/KOSDAQ) |
| `names.py` | `NameRegistry`: ticker → English name; falls back to the code, never fails |
| `market_hours.py` | `market_session()` → `pre_open / regular / closing_auction / after_hours / closed` (KST, weekdays; holidays not modelled) |
| `tracker.py` | `TickerTracker.sync(watchlist, positions)` keeps the tracked set = watchlist ∪ positions |
| `factory.py` | `MarketSettings.from_env()` and `create_market_data_source(cache, settings, names)` |
| `stream.py` | `create_stream_router(cache, names)` (a fresh router per call) and `price_events(...)` |

`backend/app/main.py`:
- `create_app()` wires the cache, the source, the name registry and the tracker into `app.state`;
- the lifespan starts and stops the source (it currently starts with `DEFAULT_TICKERS`; it should read watchlist ∪ positions once the DB exists);
- exposes `GET /api/health` and the SSE route.

Run it with `--workers 1`.

## Behaviour highlights

- **Integer KRW on real ticks.** Samsung moves in ₩100 steps; Samsung Biologics moves in ₩1,000 steps.
- **Lively but sane simulator.**
  - `SIM_TIME_SCALE=200` gives about 1 tick per step.
  - Same-sector correlation is about 0.73 (Samsung–SK Hynix); cross-sector correlation is about 0.25.
  - Jumps of 2–5% happen about once per ticker every 10 minutes, with 30% sector contagion.
  - An OU pull holds prices within about ±15% (1σ).
  - Prices are clamped to ±30% of `session_open`.
- **Deterministic tests and E2E.** Set `SIM_SEED`. Unknown tickers get a crc32-derived seed price that is stable across restarts.
- **yfinance resolution.** The listing CSV is checked first, then `.KS`, then `.KQ`.
  - Unknown tickers are rejected with `add_ticker → False`.
  - Failed lookups are not memoized, so a network blip doesn't ban a ticker.
- **yfinance polling.** One batched download per cycle, run in a worker thread.
  - NaN or missing data keeps the last price.
  - Exponential back-off up to 5 min; after 3 consecutive failures the status becomes `degraded`.
  - Only changed prices are written.
- **SSE protocol.**
  - `retry: 2000`.
  - Each event's `id` is the cache version, so clients can resume with `Last-Event-ID`.
  - An unknown or future id gets a full snapshot.
  - A `: keepalive` comment is sent after 15 s of idle.
  - The stream stops when the client disconnects.

## Configuration

| Env | Default | Meaning |
|---|---|---|
| `USE_YFINANCE` | `false` | `true` uses the yfinance poller |
| `YFINANCE_POLL_INTERVAL` | `15` | seconds |
| `SIM_SEED` | random | int for reproducible prices |
| `SIM_TIME_SCALE` | `200` | market-time speed-up |
| `SIM_EVENT_RATE` | `0.1` | jump events per ticker per minute; `0` disables them |
| `SIM_UPDATE_INTERVAL` | `0.5` | seconds per step |

Invalid values fall back to the defaults, with a warning.

## Tests (`backend/tests/`)

| Module | Covers |
|---|---|
| `market/test_ticks.py` | tick bands, snapping, limit band, ticker validation |
| `market/test_models.py` | direction, pct, exact PLAN payload |
| `market/test_cache.py` | session_open, `changed_since`, int-only, 8-thread concurrency |
| `market/test_simulator.py` | int/tick/band over 5k steps, GBM moments, factor correlations, OU half-life, determinism, jumps, unknown tickers, loop survives exceptions |
| `market/test_yfinance.py` | suffix mapping, probing, NaN/missing, back-off/degraded, DataFrame parsing (no network) |
| `market/test_conformance.py` | one contract suite run against both sources |
| `market/test_stream.py` | snapshot → deltas, resume, keepalive, headers, raw-ASGI endpoint with disconnect |
| `market/test_tracker.py`, `test_factory.py`, `test_market_hours.py`, `test_listing_names.py` | as named |
| `api/test_app.py` | lifespan start/stop, `/api/health` |

Also verified manually on 2026-11-17:
- uvicorn served `/api/health` and the live SSE stream, including `Last-Event-ID` resume;
- real yfinance returned prices for `005930.KS`, `000660.KS` and `247540.KQ`.

## Usage for downstream code

```python
from app.market import PriceCache, NameRegistry, TickerTracker, create_market_data_source, create_stream_router

cache, names = PriceCache(), NameRegistry()
source = create_market_data_source(cache, names=names)   # reads USE_YFINANCE / SIM_*
await source.start(watchlist | positions)
app.include_router(create_stream_router(cache, names))

cache.price("005930")                      # int | None — fill price for trades (reject None)
cache.get("005930")                        # PriceQuote | None
ok = await source.add_ticker("247540")     # False → respond 404 "Unknown ticker"
await TickerTracker(source).sync(watchlist, positions)   # after watchlist changes / opening or closing trades
names.get("005930")                        # "Samsung Electronics"
```

## Review items addressed

See the "Resolution" section of [`REVIEW.md`](REVIEW.md).

## Demo

```bash
cd backend && uv run market_data_demo.py   # 60 s Rich dashboard: ₩ prices, names, sparklines, jump events
```
