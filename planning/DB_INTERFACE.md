# DB Interface (`app.db`) — Seam 1

Owner: `database`. Sync stdlib `sqlite3`. Every public function opens its **own short-lived connection**, so it is safe to call from any thread (e.g. `await asyncio.to_thread(db.execute_trade, ...)`) or directly from async code (calls are sub-millisecond).

```python
from app import db
# or: from app.db import init_db, execute_trade, TradeResult, ...
```

## Path & connection

Every function takes an optional keyword-only `path: str | os.PathLike | None = None`. `None` → `get_db_path()`.

| Signature | Notes |
|---|---|
| `get_db_path() -> Path` | env `DB_PATH` (read at call time), else `<repo>/db/finally.db` (= `Path(app/db/connection.py).parents[3] / "db"`; the contract's `parents[2]` would be `backend/db`, so the repo-root intent was followed). Docker sets `DB_PATH`. |
| `init_db(path=None) -> Path` | creates parent dir, runs `backend/schema/schema.sql` (`CREATE TABLE IF NOT EXISTS`) and seed (`INSERT OR IGNORE`). Idempotent. Returns the path used. |
| `connect(path=None) -> sqlite3.Connection` | WAL, `busy_timeout=5000`, `foreign_keys=ON`, `row_factory=sqlite3.Row`, `isolation_level=None` (autocommit; explicit `BEGIN` where needed). **Lazily calls `init_db` the first time a given path is used in the process** (and again if the file was deleted). Caller closes it. |

Backend should call `init_db()` once in lifespan startup; lazy init also covers it.

## Watchlist

| Signature | Returns |
|---|---|
| `list_watchlist(*, path=None) -> list[dict]` | `[{"ticker", "name", "added_at"}]` ordered by `added_at`, then insertion |
| `add_watchlist(ticker: str, name: str, *, path=None) -> bool` | `False` if already present (no change) |
| `remove_watchlist(ticker: str, *, path=None) -> bool` | `False` if it was not present |
| `watchlist_tickers(*, path=None) -> list[str]` | convenience |

Tickers are stored exactly as given — callers pass the normalized 6-char code.

## Portfolio

| Signature | Returns |
|---|---|
| `get_cash(*, path=None) -> float` | KRW |
| `list_positions(*, path=None) -> list[dict]` | `[{"ticker", "quantity": int, "avg_cost": float, "updated_at"}]` ordered by ticker |
| `get_position(ticker, *, path=None) -> dict \| None` | same shape |
| `position_tickers(*, path=None) -> list[str]` | convenience (for `tracker.sync`) |
| `list_trades(limit: int = 50, *, path=None) -> list[dict]` | newest first: `[{"id", "ticker", "side", "quantity": int, "price": float, "executed_at"}]` |

### `execute_trade`

```python
def execute_trade(
    ticker: str,
    side: str,                 # "buy" | "sell"
    quantity: int,             # > 0
    price: int,                # fill price, > 0 (caller guarantees; never 0)
    price_lookup: Callable[[str], int | None] | None = None,
    *,
    path=None,
) -> TradeResult
```

One `BEGIN IMMEDIATE` transaction: read cash/position → validate → update cash → upsert position (weighted avg cost on buy; avg cost unchanged on sell; row **deleted** at 0) → insert trade row → insert snapshot with `total_value = cash + Σ qty × (price_lookup(t) or avg_cost)` (the traded ticker always uses the fill `price`). On validation failure nothing is written.

```python
@dataclass(frozen=True)
class TradeResult:
    success: bool
    error: str | None          # "Insufficient cash" | "Insufficient shares" | "Invalid side" | "Invalid quantity" | "Invalid price"
    ticker: str
    side: str
    quantity: int
    price: int
    cash_balance: float        # cash after the trade (current cash on failure)
    opened: bool               # a new position row was created
    closed: bool               # the position row was deleted (qty hit 0)
    total_value: float | None  # snapshot value written (None on failure)
    def to_response(self) -> dict  # PLAN §8 trade response: success shape or {"success": False, "error": ...}
```

`opened or closed` → caller should re-sync the tracker.

## Snapshots

| Signature | Returns |
|---|---|
| `record_snapshot(total_value: float, *, path=None) -> None` | |
| `last_snapshot_time(*, path=None) -> datetime \| None` | tz-aware UTC |
| `list_snapshots(limit: int \| None = None, *, path=None) -> list[dict]` | oldest→newest `[{"total_value", "recorded_at"}]` (with `limit`, the most recent `limit`, still oldest→newest) |

## Chat

| Signature | Returns |
|---|---|
| `add_chat_message(role: str, content: str, actions: dict \| None = None, *, path=None) -> str` | message id; `actions` stored as JSON text |
| `recent_chat_messages(limit: int = 20, *, path=None) -> list[dict]` | oldest→newest `[{"id", "role", "content", "actions": dict \| None, "created_at"}]` |

## Conventions

- Timestamps: ISO-8601 UTC with `Z`, millisecond precision (`2026-11-13T09:30:01.234Z`).
- IDs: `uuid4` strings.
- Seed: cash `10_000_000.0` (`INSERT OR IGNORE`); watchlist = `app.market.seed_data.DEFAULT_TICKERS` with names from `SEED_PARAMS`, inserted only once per DB file (gated by `PRAGMA user_version`) so defaults the user removed don't reappear on restart.
- Validation failures (`Invalid side/quantity/price`, `Insufficient cash/shares`) write nothing; `cash_balance` carries current cash.
- `role` is CHECK-constrained to `user`/`assistant`; `side` to `buy`/`sell`.
