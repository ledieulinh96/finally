# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation (Korean equities: KOSPI/KOSDAQ).

## Structure

- `app/main.py`: the FastAPI app (lifespan, `/api/health`, SSE). Run it with a single worker.
- `app/market/`: the market data subsystem. See `planning/MARKET_DATA_SUMMARY.md`.
  - `models.py`: `PriceQuote` (int KRW)
  - `cache.py`: thread-safe, versioned price cache
  - `base.py`: `MarketDataSource` interface
  - `simulator.py`: KRX simulator (factor-model GBM, jumps, mean reversion, ticks, ±30% limit)
  - `yfinance_source.py`: yfinance poller (~20-min delayed real prices)
  - `ticks.py`: KRX tick table and ticker validation
  - `seed_data.py`: the 10 default KOSPI tickers and their parameters
  - `listing.py` / `names.py`: bundled listing (`schema/krx_listing.csv`) and the name registry
  - `market_hours.py`: KRX session clock (KST)
  - `tracker.py`: keeps the tracked tickers equal to watchlist ∪ positions
  - `factory.py`: env-driven source selection
  - `stream.py`: the `GET /api/stream/prices` SSE endpoint
- `schema/`: SQL schema/seed (to come) and `krx_listing.csv`
- `tests/`: `market/` unit tests and `api/` app tests

## Running

```bash
uv sync --extra dev
uv run uvicorn app.main:app --port 8000 --workers 1
uv run --extra dev pytest            # tests
uv run --extra dev ruff check .      # lint
uv run market_data_demo.py           # terminal demo
```

## Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `USE_YFINANCE` | `false` | `true` polls real (~20-min delayed) prices via yfinance; otherwise the simulator runs |
| `YFINANCE_POLL_INTERVAL` | `15` | Poll period in seconds |
| `SIM_SEED` | random | Integer seed for reproducible simulator prices |
| `SIM_TIME_SCALE` | `200` | Simulator market-time speed-up |
| `SIM_EVENT_RATE` | `0.1` | Jump events per ticker per minute (`0` disables them) |
| `SIM_UPDATE_INTERVAL` | `0.5` | Seconds per simulator step |
