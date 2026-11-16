# Market Data Interface — Design

**Status:** Design for the Market Data / Backend agents · **Date:** 2026-11-16
**Related:** [`PLAN.md`](PLAN.md) §6 & §8, [`MARKET_DATA_SOURCES.md`](MARKET_DATA_SOURCES.md), [`MARKET_SIMULATOR.md`](MARKET_SIMULATOR.md)

This document defines how price data flows through the backend:
- one abstract **source** interface,
- one shared **price cache**,
- one **SSE** endpoint,

so that the simulator, the yfinance poller and any future real-time feed are interchangeable. Everything downstream of the cache knows nothing about where prices come from.

---

## 1. Design goals

1. **One interface, swappable sources.** `USE_YFINANCE` selects the implementation at startup; nothing else changes.
2. **Push-only writes, pull-only reads.** Sources write to the cache. SSE, REST and trade execution read from it. Sources never talk to clients.
3. **Integer KRW everywhere.** Prices are `int` from the source onward. No floats cross the cache boundary.
4. **Cheap SSE.** Send only tickers that changed since the client's last frame, at about 500 ms cadence.
5. **The tracked set is watchlist ∪ positions.** A stock you hold must keep a live price even after you remove it from the watchlist. Otherwise portfolio value and P&L freeze.
6. **No blocking the event loop.** Sync libraries (yfinance) run in a worker thread.
7. **Testable.** Sources can be driven step by step with an injected clock and RNG.

---

## 2. Architecture

```
            ┌──────────────────────────┐
            │  MarketDataSource (ABC)  │  ← selected by factory from USE_YFINANCE
            │  ├─ SimulatorSource      │     (future: KisWebSocketSource)
            │  └─ YFinanceSource       │
            └────────────┬─────────────┘
                         │ cache.update(ticker, price, ts)
                         ▼
            ┌──────────────────────────┐
            │       PriceCache         │  in-memory, single process
            │ ticker → PriceQuote      │  monotonically increasing version
            └──┬──────────┬─────────┬──┘
               │          │         │ read
     SSE stream│   REST   │  Trade  │
  /api/stream/ │ /api/    │ execu-  │
     prices    │ watchlist│ tion    │
               ▼          ▼         ▼
            browsers   frontend   portfolio service
```

Lifecycle is owned by FastAPI's `lifespan`. On startup:
1. build the cache;
2. build the source;
3. load the tracked tickers from the DB (watchlist ∪ positions);
4. `await source.start(tickers)`.

On shutdown: `await source.stop()`.

---

## 3. Module layout

```
backend/app/market/
├── __init__.py
├── models.py          # PriceQuote, Direction
├── cache.py           # PriceCache
├── base.py            # MarketDataSource ABC
├── simulator.py       # SimulatorSource (see MARKET_SIMULATOR.md)
├── yfinance_source.py # YFinanceSource
├── ticks.py           # KRX tick-size table + snap_to_tick()
├── factory.py         # create_source(settings, cache)
└── stream.py          # SSE router: GET /api/stream/prices
```

---

## 4. Data model

```python
# models.py
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["up", "down", "flat"]

@dataclass(frozen=True, slots=True)
class PriceQuote:
    ticker: str            # 6-char KRX code, e.g. "005930" — always str
    price: int             # KRW, tick-aligned
    prev_price: int        # price before this update
    session_open: int      # first price seen this server session
    timestamp: datetime    # tz-aware UTC
    version: int           # cache version at which this quote was written

    @property
    def direction(self) -> Direction:
        if self.price > self.prev_price:
            return "up"
        if self.price < self.prev_price:
            return "down"
        return "flat"

    @property
    def session_change_pct(self) -> float:
        if self.session_open == 0:
            return 0.0
        return round((self.price - self.session_open) / self.session_open * 100, 2)

    def to_event(self, name: str) -> dict:
        """Exact SSE payload shape from PLAN.md §6."""
        return {
            "ticker": self.ticker,
            "name": name,
            "price": self.price,
            "prev_price": self.prev_price,
            "session_open": self.session_open,
            "session_change_pct": self.session_change_pct,
            "direction": self.direction,
            "timestamp": self.timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        }
```

The quote is immutable. Each update replaces the whole object, so readers never see a half-written quote.

`name` is **not** part of the quote. Names belong to the watchlist/listing metadata and are passed in by the SSE layer. That keeps sources free of DB access.

---

## 5. PriceCache

```python
# cache.py
import threading
from datetime import datetime, timezone

class PriceCache:
    """Latest quote per ticker. Safe to write from a worker thread (yfinance)
    and read from the event loop."""

    def __init__(self) -> None:
        self._quotes: dict[str, PriceQuote] = {}
        self._version = 0
        self._lock = threading.Lock()

    def update(self, ticker: str, price: int, ts: datetime | None = None) -> PriceQuote:
        ts = ts or datetime.now(timezone.utc)
        with self._lock:
            old = self._quotes.get(ticker)
            self._version += 1
            q = PriceQuote(
                ticker=ticker,
                price=price,
                prev_price=old.price if old else price,
                session_open=old.session_open if old else price,   # first sighting = session open
                timestamp=ts,
                version=self._version,
            )
            self._quotes[ticker] = q
            return q

    def get(self, ticker: str) -> PriceQuote | None:
        return self._quotes.get(ticker)            # dict read is atomic under the GIL

    def price(self, ticker: str) -> int | None:
        q = self._quotes.get(ticker)
        return q.price if q else None

    def changed_since(self, version: int) -> list[PriceQuote]:
        with self._lock:
            return [q for q in self._quotes.values() if q.version > version]

    @property
    def version(self) -> int:
        return self._version

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._quotes.pop(ticker, None)
```

Notes:
- **`version` drives SSE deltas.** Each client remembers the highest version it has sent. `changed_since(v)` returns only newer quotes. At 10–50 tickers, scanning the dict every 500 ms costs almost nothing, so no event bus or per-client queue is needed.
- **Flat updates still bump the version.** When a poll returns the same price, `direction` becomes `"flat"` and the client gets a fresh timestamp. Sources should still skip calling `update` when nothing changed, to avoid useless SSE traffic. The simulator only writes when the tick-snapped price moves (see `MARKET_SIMULATOR.md` §7).
- **`session_open` is per server process**, as PLAN specifies. Restarting the container resets session change %.
- **Trades read `cache.price(ticker)`.** If it returns `None` (the ticker is not tracked yet), the trade endpoint must reject the trade with `"No price available"`. It must never fill at 0.

---

## 6. MarketDataSource interface

```python
# base.py
from abc import ABC, abstractmethod

class MarketDataSource(ABC):
    """Produces prices for a dynamic set of tickers and writes them to a PriceCache."""

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: set[str]) -> None:
        """Begin producing prices for `tickers`. Must return quickly; run the loop as a background task.
        Should write an initial price for every ticker before (or very soon after) returning,
        so the first SSE frame and the first REST call are not empty."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel background work and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> bool:
        """Start tracking `ticker`. Returns False if the source cannot price it
        (e.g. yfinance finds neither .KS nor .KQ). Idempotent."""

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking `ticker` and drop it from the cache. Idempotent."""

    @property
    @abstractmethod
    def tickers(self) -> frozenset[str]: ...

    @property
    def status(self) -> str:
        """'ok' | 'degraded' | 'stopped' — surfaced by GET /api/health."""
        return "ok"
```

Contract details every implementation must follow:

| Rule | Why |
|---|---|
| Prices written to the cache are `int`, > 0, and tick-aligned | Frontend shows integers; trades fill at a valid KRX price |
| `add_ticker` writes a first price before returning `True` | The UI can show the new row immediately |
| Errors inside the loop are logged and swallowed; the loop never dies | One bad ticker or network blip must not kill streaming |
| `status = "degraded"` after repeated failures | Health check and UI connection dot can reflect it |
| No DB access inside sources | Keeps sources testable; the API layer owns persistence |

### 6.1 Factory

```python
# factory.py
def create_source(settings, cache: PriceCache) -> MarketDataSource:
    if settings.use_yfinance:
        from .yfinance_source import YFinanceSource       # lazy import: yfinance is optional at runtime
        return YFinanceSource(cache, poll_interval=15.0)
    from .simulator import SimulatorSource
    return SimulatorSource(cache, update_interval=0.5, seed=settings.sim_seed)
```

### 6.2 YFinanceSource sketch

```python
class YFinanceSource(MarketDataSource):
    def __init__(self, cache, poll_interval=15.0):
        super().__init__(cache)
        self._symbols: dict[str, str] = {}      # "005930" -> "005930.KS"
        self._task: asyncio.Task | None = None
        self._interval = poll_interval
        self._failures = 0

    async def start(self, tickers):
        for t in tickers:
            await self.add_ticker(t)
        self._task = asyncio.create_task(self._run())

    async def add_ticker(self, ticker):
        if ticker in self._symbols:
            return True
        symbol = await asyncio.to_thread(resolve_symbol, ticker)   # listing CSV → .KS → .KQ probe
        if not symbol:
            return False
        self._symbols[ticker] = symbol
        price = await asyncio.to_thread(fetch_last_price, symbol)
        if price:
            self.cache.update(ticker, snap_to_tick(price))
        return True

    async def _run(self):
        while True:
            try:
                prices = await asyncio.to_thread(fetch_batch, list(self._symbols.values()))
                for ticker, symbol in list(self._symbols.items()):
                    p = prices.get(symbol)
                    if p and p != self.cache.price(ticker):
                        self.cache.update(ticker, snap_to_tick(p))
                self._failures = 0
                delay = self._interval
            except Exception:
                log.exception("yfinance poll failed")
                self._failures += 1
                delay = min(self._interval * 2 ** self._failures, 300)   # back-off to 5 min
            await asyncio.sleep(delay)
```

`fetch_batch` wraps a single `yf.download(...)` (see `MARKET_DATA_SOURCES.md` §4.1). `status` returns `"degraded"` while `_failures >= 3`.

---

## 7. SSE endpoint — `GET /api/stream/prices`

### 7.1 Protocol

```
HTTP/1.1 200 OK
Content-Type: text/event-stream
Cache-Control: no-cache
X-Accel-Buffering: no

retry: 2000                          ← reconnect delay hint for EventSource

id: 1542                             ← cache version; lets the browser resume
data: {"ticker":"005930","name":"Samsung Electronics","price":75400,...}

id: 1543
data: {"ticker":"000660",...}

: keepalive                          ← comment line every 15 s when idle
```

Decisions:
- **One event per ticker**, matching the PLAN payload exactly. Frontend code stays `JSON.parse(e.data)` → update one row.
  - *Alternative considered:* a batch array per frame, which means fewer frames. It was rejected because PLAN fixes the per-ticker shape and at about 10–50 tickers × 2 Hz the overhead is negligible.
- **Initial snapshot.** On connect, send the current quote for every tracked ticker immediately, so the grid fills before the first tick.
- **Resume.** `EventSource` resends `Last-Event-ID` after a reconnect. Use it as the starting version, so the client only receives what it missed. Quotes are "latest value" data, so a full snapshot on reconnect is also acceptable.
- **Keepalive** comments every 15 s stop proxies from closing idle connections. This matters with yfinance, which may produce no updates for minutes.
- **Disconnect detection.** Check `await request.is_disconnected()` each loop iteration and exit.

### 7.2 Implementation sketch

```python
# stream.py
router = APIRouter()

@router.get("/api/stream/prices")
async def stream_prices(request: Request,
                        cache: PriceCache = Depends(get_cache),
                        names: NameRegistry = Depends(get_names)):
    last_id = request.headers.get("last-event-id")
    since = int(last_id) if last_id and last_id.isdigit() else 0

    async def gen():
        nonlocal since
        yield "retry: 2000\n\n"
        idle = 0.0
        while not await request.is_disconnected():
            quotes = cache.changed_since(since)
            if quotes:
                for q in sorted(quotes, key=lambda q: q.version):
                    payload = json.dumps(q.to_event(names.get(q.ticker)), separators=(",", ":"))
                    yield f"id: {q.version}\ndata: {payload}\n\n"
                    since = max(since, q.version)
                idle = 0.0
            else:
                idle += 0.5
                if idle >= 15:
                    yield ": keepalive\n\n"
                    idle = 0.0
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

`since = 0` on first connect produces the initial snapshot for free, because every quote has a version > 0.

**Removed tickers:** SSE only sends updates, never deletions. The frontend learns about removals from the `DELETE /api/watchlist/{ticker}` response, or from the chat response's `watchlist_changes`. It drops the row itself and ignores stray events for tickers it no longer shows.

---

## 8. Tracked-ticker management

The tracked set is **watchlist ∪ open positions**. One small service owns it, so routes don't each re-implement the rule:

```python
class TickerTracker:
    def __init__(self, source: MarketDataSource, db): ...

    async def sync(self) -> None:
        wanted = await db.watchlist_tickers() | await db.position_tickers()
        for t in wanted - self.source.tickers:
            await self.source.add_ticker(t)
        for t in self.source.tickers - wanted:
            await self.source.remove_ticker(t)
```

Call `tracker.sync()` after:
- watchlist add or remove (REST or chat);
- a trade that opens a new position;
- a sell that closes a position completely.

| Event | Effect |
|---|---|
| `POST /api/watchlist {ticker}` | Validate format `^[0-9A-Z]{6}$` → `source.add_ticker`. If it returns `False`, respond **404 "Unknown ticker"** and do not insert into the DB. Otherwise insert and resolve the name (listing CSV → OpenDART → yfinance `shortName`). |
| `DELETE /api/watchlist/{ticker}` | Delete the row, then `sync()`. If the ticker is still held, it stays tracked. |
| Buy of a non-watched ticker | Requires a price. If the ticker isn't tracked, `add_ticker` first, then fill at the cached price. |
| Sell to zero | Row deleted, then `sync()`. |

The **name registry** (`ticker → English name`) is loaded from the watchlist table plus the listing CSV and updated when tickers are added. The SSE layer and `GET /api/portfolio` use it, which fixes the "position name is missing after its watchlist row is removed" gap found in review.

---

## 9. REST consumers of the cache

| Endpoint | Reads |
|---|---|
| `GET /api/watchlist` | `cache.get(t)` for each watchlist row → `price`, `prev_price`, `session_change_pct`, `direction`. `price: null` if not yet priced. |
| `GET /api/portfolio` | `cache.price(t)` per position for `current_price`, `market_value`, `unrealized_pnl`. If no price yet, fall back to `avg_cost`, so P&L is 0 rather than an error. |
| `POST /api/portfolio/trade` | `cache.price(ticker)` is the fill price. Rejects if `None`. |
| `POST /api/chat` | Portfolio context built from the same reads. |
| `GET /api/health` | `{"status": "ok", "market_data": source.status, "source": "simulator" or "yfinance"}` |

---

## 10. Frontend contract (summary for the Frontend agent)

- `const es = new EventSource("/api/stream/prices")`. Use `onmessage`, because events have no `event:` name.
- Connection dot:
  - **green** after `onopen` and while messages or keepalives arrive;
  - **yellow** on `onerror` while `es.readyState === EventSource.CONNECTING`;
  - **red** when `readyState === CLOSED`, or when nothing has arrived for more than 30 s.
- Flash animation: driven by `direction`. `"flat"` means no flash.
- Sparklines: append `price` per ticker to a capped ring buffer, for example the last 300 points ≈ 2.5 min at 2 Hz.
- Prices are integers: format with `"₩" + price.toLocaleString("ko-KR")`.

---

## 11. Testing plan

| Test | How |
|---|---|
| Cache semantics | `update` sets `prev_price` and keeps `session_open`; `changed_since` returns only newer versions; concurrent writes from threads don't lose updates. |
| `PriceQuote.to_event` | Matches the PLAN JSON shape exactly; timestamp ends with `Z`; `session_change_pct` is rounded to 2 dp. |
| Interface conformance | One parametrized test suite runs against `SimulatorSource` and a `YFinanceSource` with a stubbed fetcher. It checks: start → every ticker priced; add/remove idempotent; prices int and tick-aligned; stop idempotent. |
| yfinance mapping | `005930` → `005930.KS`; a KOSDAQ code → `.KQ` via the listing; unknown → `add_ticker` returns `False`; NaN rows are skipped and the last price is kept. Uses recorded fixtures, no network. |
| SSE | `httpx.AsyncClient` stream: first frames are a full snapshot; later frames contain only changed tickers; `Last-Event-ID` resumes; disconnect ends the generator. |
| Tracker | Removing a held ticker from the watchlist keeps it tracked; selling to zero then removing untracks it. |
