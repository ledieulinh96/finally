# Services Interface (Seam 2) — `backend/app/services`

Owner: `backend`. Consumers: `backend/app/api` (REST routes) and `backend/app/llm` (chat flow).
Both go through the **same** `PortfolioService`, so validation and side effects are identical.

## Getting the service

```python
from app.services import PortfolioService, ServiceError  # and the error subclasses below

services: PortfolioService = request.app.state.services   # in a route
# POST /api/chat calls:  await app.llm.handle_chat(message, services)
```

All methods are `async` (DB work runs in `asyncio.to_thread`). Never raise for business-rule
failures of `trade()`; watchlist methods raise typed errors (below).

## Methods

### `async trade(ticker: str, side: str, quantity: int) -> dict`
Never raises. Validates & executes a market order at the cached price.
- Ticker normalized with `normalize_ticker` (strip, upper, `.KS`/`.KQ` stripped). Bad → `"Invalid ticker"`.
- `side` must be `"buy"`/`"sell"`; `quantity` must be a positive `int` (bools/floats rejected) → `"Invalid side"` / `"Invalid quantity"`.
- If the ticker has no cached price: `tracker.ensure(ticker)`; still none → `"No price available"`. Never fills at 0.
- DB failures: `"Insufficient cash"`, `"Insufficient shares"`.
- After a trade that opens or closes a position the tracker is re-synced (watchlist ∪ positions).

Success (PLAN §8):
```json
{"success": true, "ticker": "005930", "side": "buy", "quantity": 5, "price": 75400, "cash_balance": 8123000}
```
Failure: `{"success": false, "error": "Insufficient cash"}`

### `async add_watchlist(ticker: str, name: str | None = None) -> dict`
Returns `{"ticker": "247540", "name": "EcoPro BM", "price": 86200}` (`price` may be `null`).
Name resolution when `name` is omitted: NameRegistry (bundled `krx_listing.csv` + defaults + names seen
from the source, e.g. yfinance `shortName`) → optional async name resolvers registered by other
modules (e.g. OpenDART `corp_name_eng`, see below) → the ticker code. The final name is stored in the
`watchlist` table and in the NameRegistry. Tracker is re-synced.

Raises:
| Error | When | REST status |
|---|---|---|
| `InvalidTickerError` | ticker fails `^[0-9A-Z]{6}$` | 422 |
| `AlreadyInWatchlistError` | already watched | 409 |
| `UnknownTickerError` | source can't price it (yfinance: no `.KS`/`.KQ` data). Row is NOT kept. | 404 |

### `async remove_watchlist(ticker: str) -> dict`
Returns `{"ticker": "035720", "removed": true}`. Re-syncs the tracker (a held ticker keeps streaming).
Raises `InvalidTickerError` (422) or `NotInWatchlistError` (404).

All errors subclass `ServiceError` (`.status_code: int`, `str(err)` = human message). The chat flow
should catch `ServiceError` and report `{"success": false, "error": str(err)}`.

### `async portfolio() -> dict` — PLAN §8 `GET /api/portfolio` shape
```json
{"cash_balance": 8500000, "total_value": 10200000, "positions": [
  {"ticker": "005930", "name": "Samsung Electronics", "quantity": 10, "avg_cost": 74000,
   "current_price": 75400, "market_value": 754000, "unrealized_pnl": 14000, "pnl_pct": 1.89}]}
```
`current_price` falls back to `avg_cost` when unpriced. `pnl_pct` rounded to 2dp. Quantities are ints.

### `async watchlist() -> list[dict]` — PLAN §8 `GET /api/watchlist` shape
`[{"ticker","name","price","prev_price","session_open","session_change_pct","direction"}]`;
price fields `null` and `direction: "flat"` when unpriced.

### `async history() -> list[dict]` — `[{"total_value", "recorded_at"}]`, oldest first. Read-only.

### `async chat_history(limit=50) -> list[dict]` — `GET /api/chat/history`
Oldest first: `[{"id","role","content","trades","watchlist_changes","created_at"}]` (lists empty for user rows).

### Helpers (sync)
- `name(ticker) -> str` — NameRegistry lookup (falls back to the code).
- `price(ticker) -> int | None` — cached price.
- `add_name_resolver(fn)` — register `async fn(ticker: str) -> str | None` used by `add_watchlist`
  when the registry has no name. `main.py` registers `app.llm.dart.resolve_name` (OpenDART
  `corp_name_eng`; returns None without `OPENDART_API_KEY`).
- `async snapshot_if_due(min_age=60.0) -> bool` — serialized by a lock; the lifespan takes a
  startup snapshot, then `run_snapshots()` checks every 60 s.

## Attributes (read-only use)
`services.cache` (PriceCache), `services.names` (NameRegistry), `services.tracker`, `services.source`.
