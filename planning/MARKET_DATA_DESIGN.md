# Market Data Design

Implementation-ready design for the FinAlly market data backend: the price model, cache, both data sources (GBM simulator and Massive REST poller), SSE streaming, watchlist/position tracking, and FastAPI wiring. Every code block below was run against the real `massive` SDK and FastAPI in a scratch copy of `backend/` (96 tests passing, `ruff` clean, served by uvicorn and checked with `curl`).

This supersedes `planning/archive/MARKET_DATA_DESIGN.md`. That document describes the subsystem as first built; this one describes it **as it should be**, including the fixes and missing integration pieces the platform build will need.

---

## Contents

1. [Status and what changes](#1-status-and-what-changes)
2. [Architecture](#2-architecture)
3. [File layout](#3-file-layout)
4. [Ticker normalization — `tickers.py`](#4-ticker-normalization--tickerspy)
5. [Price model — `models.py`](#5-price-model--modelspy)
6. [Price cache — `cache.py`](#6-price-cache--cachepy)
7. [Source interface — `interface.py`](#7-source-interface--interfacepy)
8. [Seed data — `seed_prices.py`](#8-seed-data--seed_pricespy)
9. [GBM simulator — `simulator.py`](#9-gbm-simulator--simulatorpy)
10. [Massive poller — `massive_client.py`](#10-massive-poller--massive_clientpy)
11. [Source selection — `factory.py`](#11-source-selection--factorypy)
12. [SSE streaming — `stream.py`](#12-sse-streaming--streampy)
13. [Watchlist and position tracking — `tracking.py`](#13-watchlist-and-position-tracking--trackingpy)
14. [App wiring — `app/main.py`](#14-app-wiring--appmainpy)
15. [Downstream consumers](#15-downstream-consumers)
16. [Tests](#16-tests)
17. [Edge cases and error handling](#17-edge-cases-and-error-handling)
18. [Configuration](#18-configuration)
19. [Implementation checklist](#19-implementation-checklist)

---

## 1. Status and what changes

`backend/app/market/` exists with 8 modules and 73 passing tests. Reviewing it against `PLAN.md` and the installed `massive` SDK turned up these issues:

| # | Severity | Issue | Fix (section) |
|---|---|---|---|
| 1 | **Critical** | `MassiveDataSource` reads `snap.last_trade.timestamp`, but the SDK's `LastTrade` has no such attribute (it's `sip_timestamp`, in **nanoseconds**). With a real API key every snapshot raises `AttributeError`, gets skipped, and **the cache never receives a price**. The tests miss this because they use `MagicMock` snapshots, which accept any attribute. | §10, §16.1 |
| 2 | High | `PLAN.md` asks for a **daily change %** in the watchlist, but `PriceUpdate.change_percent` is tick-to-tick (~0.01%). There's no session baseline. | §5, §6, §10 |
| 3 | High | No `app/main.py`: nothing starts the source, mounts the SSE router, or stops it on shutdown. A static mount at `/` added before the router would also shadow `/api/stream/prices`. | §14 |
| 4 | Medium | Removing a watchlist ticker stops its prices even if the user **holds** it, which breaks portfolio valuation. | §13 |
| 5 | Medium | Trading a ticker that isn't streaming has no price path. | §13 |
| 6 | Medium | `stream.py` registers the route on a module-level router each time `create_stream_router()` runs, so calling it twice registers the route twice (review item 3.6, still open). | §12 |
| 7 | Low | Ticker case is normalized only in the Massive client; the simulator would track `aapl` and `AAPL` separately. | §4 |
| 8 | Low | `PriceCache.update(..., timestamp=0.0)` is treated as "no timestamp" (`timestamp or time.time()`); `version` is read without the lock; `remove()` doesn't bump `version`, so SSE clients never see a removal. | §6 |
| 9 | Low | No SSE heartbeat. With Massive at 15 s intervals, idle proxies can drop the connection between polls. | §12 |
| 10 | Info | `planning/archive/MASSIVE_API.md` documents `day.previous_close` and `day.change_percent`. Those fields don't exist on the SDK model; the real ones are `prev_day.close` and `todays_change_percent`. | §10 |

Modules that are **unchanged**: `interface.py`, and the GBM maths in `simulator.py`. Everything else gets small, additive edits. Two new modules: `tickers.py` and `tracking.py`.

---

## 2. Architecture

```
                     MASSIVE_API_KEY set?
                    ┌─────────┴─────────┐
                    no                  yes
                    ▼                   ▼
          SimulatorDataSource     MassiveDataSource
          (GBM, every 0.5 s)      (REST snapshot, every 15 s)
                    │                   │
                    └──── writes ───────┘
                              ▼
                    PriceCache  (thread-safe, latest price per ticker, version counter)
                              │
      ┌───────────────┬───────┴──────────┬────────────────────┬──────────────────┐
      ▼               ▼                  ▼                    ▼                  ▼
 SSE /api/stream   GET /api/watchlist  POST /api/portfolio   snapshot task     chat context
 /prices (0.5 s)   (latest prices)     /trade (fill price)   (every 30 s)      (LLM prompt)

 Watchlist + positions (SQLite) ──► sync_tracked_tickers() ──► source.add_ticker / remove_ticker
```

Rules:

- **One writer, many readers.** Only the active data source writes to the cache. Everything else reads it.
- **Nobody asks the source for a price.** Consumers read `PriceCache`. The source only takes lifecycle calls (`start`, `stop`, `add_ticker`, `remove_ticker`).
- **Tracked set = watchlist ∪ open positions.** `tracking.py` is the only code that decides what the source tracks.
- **Symbols are normalized at the edge.** Every ticker entering the subsystem goes through `normalize_ticker()`.

---

## 3. File layout

```
backend/
  app/
    main.py                   # NEW  FastAPI app, lifespan, router + static mount order
    market/
      __init__.py             # re-exports (add normalize_ticker, sync_tracked_tickers, ...)
      tickers.py              # NEW  normalize_ticker(), InvalidTickerError
      models.py               # EDIT +reference_price, +day_change, +day_change_percent
      cache.py                # EDIT reference carry-forward, version under lock, remove() bumps version
      interface.py            #      unchanged
      seed_prices.py          # EDIT +DEFAULT_TICKERS
      simulator.py            # EDIT normalize tickers in SimulatorDataSource
      massive_client.py       # EDIT parse_snapshot() with correct SDK fields (bug fix)
      factory.py              # EDIT MASSIVE_POLL_INTERVAL
      stream.py               # EDIT router per call, id: field, heartbeat, testable generator
      tracking.py             # NEW  sync_tracked_tickers(), get_price_or_wait()
  tests/market/
      test_massive.py         # REWRITE using real TickerSnapshot objects
      test_stream.py          # NEW
      test_tracking.py        # NEW
      test_cache.py           # EDIT +TestReferencePrice
```

Public API (`app/market/__init__.py`):

```python
from .cache import PriceCache
from .factory import create_market_data_source
from .interface import MarketDataSource
from .models import PriceUpdate
from .stream import create_stream_router
from .tickers import InvalidTickerError, normalize_ticker
from .tracking import PriceUnavailableError, get_price_or_wait, sync_tracked_tickers

__all__ = [
    "PriceUpdate", "PriceCache", "MarketDataSource", "create_market_data_source",
    "create_stream_router", "normalize_ticker", "InvalidTickerError",
    "sync_tracked_tickers", "get_price_or_wait", "PriceUnavailableError",
]
```

---

## 4. Ticker normalization — `tickers.py`

One function cleans every symbol, whether it came from the watchlist API, the trade bar, or the LLM's structured output. Routes catch `InvalidTickerError` and return `400`.

```python
"""Ticker symbol normalization and validation — the single place symbols are cleaned."""

from __future__ import annotations

import re

# 1-5 letters, optionally followed by a class suffix: BRK.B, BF-B
_TICKER_RE = re.compile(r"^[A-Z]{1,5}([.\-][A-Z]{1,2})?$")


class InvalidTickerError(ValueError):
    """Raised when a ticker symbol is malformed."""


def normalize_ticker(raw: str) -> str:
    """Upper-case, strip, and validate a ticker symbol.

    >>> normalize_ticker(" aapl ")
    'AAPL'
    """
    ticker = (raw or "").strip().upper()
    if not _TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError(f"Invalid ticker symbol: {raw!r}")
    return ticker
```

The pattern accepts common US equity symbols (`AAPL`, `BRK.B`, `BF-B`) and rejects anything that could be junk or injection (`$AAPL`, `AAPL;DROP`, `A1`, empty). It checks format only; whether a symbol *exists* is decided by the data source (§17).

---

## 5. Price model — `models.py`

`PriceUpdate` is the only type that leaves the market layer. The new field is `reference_price`, the baseline for the watchlist's **daily change %**:

| Source | `reference_price` means |
|---|---|
| Massive | Previous session close (`prev_day.close`) — the standard "today's change" baseline |
| Simulator | The ticker's first price this process (seed price, or price when added) |

```python
"""Data models for market data."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """Immutable snapshot of a single ticker's price at a point in time."""

    ticker: str
    price: float
    previous_price: float
    timestamp: float = field(default_factory=time.time)  # Unix seconds
    # Baseline for "daily change": previous close (Massive) or the price when
    # the ticker started being tracked (simulator). None → same as price.
    reference_price: float | None = None

    @property
    def change(self) -> float:
        """Absolute change since the previous tick."""
        return round(self.price - self.previous_price, 4)

    @property
    def change_percent(self) -> float:
        """Percent change since the previous tick."""
        if self.previous_price == 0:
            return 0.0
        return round((self.price - self.previous_price) / self.previous_price * 100, 4)

    @property
    def direction(self) -> str:
        """'up', 'down', or 'flat' relative to the previous tick."""
        if self.price > self.previous_price:
            return "up"
        if self.price < self.previous_price:
            return "down"
        return "flat"

    @property
    def day_change(self) -> float:
        """Absolute change since the reference (session) price."""
        ref = self.reference_price if self.reference_price is not None else self.price
        return round(self.price - ref, 4)

    @property
    def day_change_percent(self) -> float:
        """Percent change since the reference (session) price."""
        ref = self.reference_price if self.reference_price is not None else self.price
        if ref == 0:
            return 0.0
        return round((self.price - ref) / ref * 100, 4)

    def to_dict(self) -> dict:
        """Serialize for JSON / SSE transmission."""
        return {
            "ticker": self.ticker,
            "price": self.price,
            "previous_price": self.previous_price,
            "reference_price": self.reference_price,
            "timestamp": self.timestamp,
            "change": self.change,
            "change_percent": self.change_percent,
            "day_change": self.day_change,
            "day_change_percent": self.day_change_percent,
            "direction": self.direction,
        }
```

Two kinds of change, used for different things:

| Field | Baseline | UI use |
|---|---|---|
| `direction`, `change`, `change_percent` | previous tick | green/red flash |
| `day_change`, `day_change_percent` | `reference_price` | watchlist "Chg %" column |

Example `to_dict()` output, as captured from the running server:

```json
{
  "ticker": "AAPL",
  "price": 190.01,
  "previous_price": 190.0,
  "reference_price": 190.0,
  "timestamp": 1794840735.5910459,
  "change": 0.01,
  "change_percent": 0.0053,
  "day_change": 0.01,
  "day_change_percent": 0.0053,
  "direction": "up"
}
```

---

## 6. Price cache — `cache.py`

```python
"""Thread-safe in-memory price cache."""

from __future__ import annotations

import time
from threading import Lock

from .models import PriceUpdate


class PriceCache:
    """Thread-safe in-memory cache of the latest price for each ticker.

    Writers: SimulatorDataSource or MassiveDataSource (one at a time).
    Readers: SSE streaming endpoint, portfolio valuation, trade execution.
    """

    def __init__(self) -> None:
        self._prices: dict[str, PriceUpdate] = {}
        self._lock = Lock()
        self._version: int = 0  # Monotonically increasing; bumped on every write

    def update(
        self,
        ticker: str,
        price: float,
        timestamp: float | None = None,
        reference_price: float | None = None,
    ) -> PriceUpdate:
        """Record a new price. Returns the stored PriceUpdate.

        - previous_price is the last cached price (or `price` on first write).
        - reference_price, if not given, is carried forward from the previous
          update; on first write it defaults to `price` (session start).
        """
        with self._lock:
            ts = timestamp if timestamp is not None else time.time()
            prev = self._prices.get(ticker)
            previous_price = prev.price if prev else price
            if reference_price is None:
                reference_price = prev.reference_price if prev else price

            update = PriceUpdate(
                ticker=ticker,
                price=round(price, 2),
                previous_price=round(previous_price, 2),
                timestamp=ts,
                reference_price=round(reference_price, 2),
            )
            self._prices[ticker] = update
            self._version += 1
            return update

    def get(self, ticker: str) -> PriceUpdate | None:
        with self._lock:
            return self._prices.get(ticker)

    def get_all(self) -> dict[str, PriceUpdate]:
        """Shallow copy of all current prices."""
        with self._lock:
            return dict(self._prices)

    def get_price(self, ticker: str) -> float | None:
        update = self.get(ticker)
        return update.price if update else None

    def remove(self, ticker: str) -> None:
        """Drop a ticker. Bumps the version so SSE clients see the removal."""
        with self._lock:
            if self._prices.pop(ticker, None) is not None:
                self._version += 1

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._prices)

    def __contains__(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._prices
```

Changes from the current version:

- **`reference_price` carry-forward.** Sources that know a baseline (Massive) pass it each time. Sources that don't (simulator) pass nothing, and the first price becomes the baseline. No simulator change is needed for daily change % to work.
- **`timestamp is not None`** instead of `timestamp or ...`, so `0.0` is a valid timestamp.
- **`remove()` bumps `version`** only when something was actually removed. Without this, an SSE client keeps showing a removed ticker until the next price tick. With Massive that can be 15 s.
- **`version` reads under the lock.** Free on CPython today; correct on free-threaded builds.

Why a `threading.Lock` and not an `asyncio.Lock`: Massive's SDK is synchronous and runs via `asyncio.to_thread`. Writes happen on the event loop today, but reads and writes are tiny, so a plain lock is simpler and safe from any thread.

---

## 7. Source interface — `interface.py`

Unchanged. Shown for reference:

```python
class MarketDataSource(ABC):
    async def start(self, tickers: list[str]) -> None: ...   # seed cache, start background task
    async def stop(self) -> None: ...                        # cancel task; idempotent
    async def add_ticker(self, ticker: str) -> None: ...     # no-op if present
    async def remove_ticker(self, ticker: str) -> None: ...  # no-op if absent; also evicts from cache
    def get_tickers(self) -> list[str]: ...
```

Contract details implementations must honour:

- `start()` must leave the cache **populated** before it returns (the simulator seeds; Massive does one blocking poll). The first SSE frame then has data.
- `add_ticker()` / `remove_ticker()` accept un-normalized input and normalize it themselves.
- `remove_ticker()` always calls `cache.remove()`, even if the source didn't know the ticker.

---

## 8. Seed data — `seed_prices.py`

Add `DEFAULT_TICKERS` so the DB seed logic and the startup fallback share one list:

```python
# Default watchlist, in display order (seeded into the DB on first run)
DEFAULT_TICKERS: list[str] = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
```

Existing parameters (unchanged):

| Ticker | Seed | σ (annual vol) | μ (annual drift) | Group |
|---|---:|---:|---:|---|
| AAPL | 190 | 0.22 | 0.05 | tech |
| GOOGL | 175 | 0.25 | 0.05 | tech |
| MSFT | 420 | 0.20 | 0.05 | tech |
| AMZN | 185 | 0.28 | 0.05 | tech |
| TSLA | 250 | 0.50 | 0.03 | own (ρ = 0.3 with all) |
| NVDA | 800 | 0.40 | 0.08 | tech |
| META | 500 | 0.30 | 0.05 | tech |
| JPM | 195 | 0.18 | 0.04 | finance |
| V | 280 | 0.17 | 0.04 | finance |
| NFLX | 600 | 0.35 | 0.05 | tech |
| *other* | U(50, 300) | 0.25 | 0.05 | ρ = 0.3 |

Correlations: tech–tech 0.6, finance–finance 0.5, everything else 0.3.

---

## 9. GBM simulator — `simulator.py`

### 9.1 Maths (unchanged)

Each 500 ms tick, for every ticker *i*:

```
S_i(t+dt) = S_i(t) · exp( (μ_i − σ_i²/2)·dt + σ_i·√dt·Z_i )

dt = 0.5 s / (252 days × 6.5 h × 3600 s) ≈ 8.48e-8 trading-years
Z  = L · ε,   ε ~ N(0, I),   L = cholesky(C)   (C = sector correlation matrix)
```

Then, with probability 0.001 per ticker per tick, a shock multiplies the price by `1 ± U(0.02, 0.05)`. With 10 tickers at 2 ticks/s that's about one visible "event" every 50 s.

What this produces at 0.5 s ticks (σ = 0.22, AAPL at $190): per-tick σ ≈ 0.22 × √8.48e-8 ≈ 0.0064%, about **1.2¢ per tick**. That's enough for constant green/red flashes and sparkline movement without unrealistic drift.

The hot path (current code):

```python
def step(self) -> dict[str, float]:
    n = len(self._tickers)
    if n == 0:
        return {}
    z = np.random.standard_normal(n)
    if self._cholesky is not None:
        z = self._cholesky @ z                      # correlate
    result = {}
    for i, ticker in enumerate(self._tickers):
        mu, sigma = self._params[ticker]["mu"], self._params[ticker]["sigma"]
        drift = (mu - 0.5 * sigma**2) * self._dt
        diffusion = sigma * math.sqrt(self._dt) * z[i]
        self._prices[ticker] *= math.exp(drift + diffusion)
        if random.random() < self._event_prob:      # occasional 2-5% shock
            self._prices[ticker] *= 1 + random.uniform(0.02, 0.05) * random.choice([-1, 1])
        result[ticker] = round(self._prices[ticker], 2)
    return result
```

Adding or removing a ticker rebuilds the Cholesky factor (O(n³), negligible for n < 50). A constant-off-diagonal matrix with ρ ∈ [0.3, 0.6] is always positive-definite, so `np.linalg.cholesky` can't fail on the matrices this code builds.

### 9.2 Required edit: normalize in `SimulatorDataSource`

```python
from .tickers import normalize_ticker

class SimulatorDataSource(MarketDataSource):
    async def start(self, tickers: list[str]) -> None:
        tickers = list(dict.fromkeys(normalize_ticker(t) for t in tickers))  # dedupe, keep order
        self._sim = GBMSimulator(tickers=tickers, event_probability=self._event_prob)
        for ticker in tickers:                       # seed cache → SSE has data immediately
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)
        self._task = asyncio.create_task(self._run_loop(), name="simulator-loop")

    async def add_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if self._sim:
            self._sim.add_ticker(ticker)
            price = self._sim.get_price(ticker)
            if price is not None:
                self._cache.update(ticker=ticker, price=price)   # price available synchronously

    async def remove_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if self._sim:
            self._sim.remove_ticker(ticker)
        self._cache.remove(ticker)
```

Because `add_ticker` seeds the cache before returning, a trade on a brand-new ticker in simulator mode gets a fill price with no wait (§13).

### 9.3 Tuning knobs

| Knob | Where | Effect |
|---|---|---|
| `update_interval` | `SimulatorDataSource(update_interval=0.5)` | Tick rate. Keep at the SSE push cadence. |
| `event_probability` | `SimulatorDataSource(event_probability=0.001)` | Shock frequency. `0` for deterministic-ish tests. |
| `TICKER_PARAMS` | `seed_prices.py` | Per-ticker σ/μ. |
| `np.random.seed(n)` + `random.seed(n)` | tests | Reproducible paths. |

---

## 10. Massive poller — `massive_client.py`

### 10.1 The bug and the correct SDK fields

Checked against the installed SDK (`massive.rest.models.TickerSnapshot`):

| We need | Correct attribute | Notes |
|---|---|---|
| Price | `snap.last_trade.price` | Fall back to `snap.min.close`, then `snap.day.close` (pre-market/thin tickers) |
| Timestamp | `snap.last_trade.sip_timestamp` | **Nanoseconds**. Fall back to `snap.updated` (also ns) |
| Daily baseline | `snap.prev_day.close` | Not `day.previous_close`, which doesn't exist |
| Day change % (unused, for reference) | `snap.todays_change_percent` | Not `day.change_percent` |

Current code: `snap.last_trade.timestamp / 1000.0` raises `AttributeError` on every real snapshot. Reproduce it:

```python
from massive.rest.models import TickerSnapshot
s = TickerSnapshot.from_dict({"ticker": "AAPL", "lastTrade": {"p": 190.5, "t": 1707580800123456789}})
s.last_trade.sip_timestamp   # 1707580800123456789
s.last_trade.timestamp       # AttributeError: 'LastTrade' object has no attribute 'timestamp'
```

### 10.2 Implementation

Parsing moves into a pure function, `parse_snapshot()`, that can be unit-tested with real SDK objects built via `TickerSnapshot.from_dict(...)`.

```python
"""Massive (Polygon.io) API client for real market data."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import NamedTuple

from massive import RESTClient
from massive.rest.models import SnapshotMarketType, TickerSnapshot

from .cache import PriceCache
from .interface import MarketDataSource
from .tickers import normalize_ticker

logger = logging.getLogger(__name__)

NS_PER_SECOND = 1_000_000_000


class ParsedSnapshot(NamedTuple):
    ticker: str
    price: float
    timestamp: float  # Unix seconds
    reference_price: float | None  # previous session close


def parse_snapshot(snap: TickerSnapshot) -> ParsedSnapshot | None:
    """Turn a Massive TickerSnapshot into the fields we cache. None if unusable.

    Price preference: last trade → current minute bar close → day bar close.
    Timestamps in the snapshot endpoint are Unix *nanoseconds*.
    """
    if not snap.ticker:
        return None

    lt = snap.last_trade
    price = lt.price if lt and lt.price else None
    if price is None and snap.min and snap.min.close:
        price = snap.min.close
    if price is None and snap.day and snap.day.close:
        price = snap.day.close
    if price is None or price <= 0:
        return None

    ts_ns = (lt.sip_timestamp if lt else None) or snap.updated
    timestamp = ts_ns / NS_PER_SECOND if ts_ns else time.time()

    ref = snap.prev_day.close if snap.prev_day and snap.prev_day.close else None
    return ParsedSnapshot(snap.ticker, float(price), timestamp, ref)


class MassiveDataSource(MarketDataSource):
    """Polls GET /v2/snapshot/locale/us/markets/stocks/tickers for all tracked
    tickers in one call per interval and writes results to the PriceCache."""

    def __init__(self, api_key: str, price_cache: PriceCache, poll_interval: float = 15.0) -> None:
        self._api_key = api_key
        self._cache = price_cache
        self._interval = poll_interval
        self._tickers: list[str] = []
        self._task: asyncio.Task | None = None
        self._client: RESTClient | None = None

    async def start(self, tickers: list[str]) -> None:
        self._client = RESTClient(api_key=self._api_key)
        self._tickers = list(dict.fromkeys(normalize_ticker(t) for t in tickers))
        await self._poll_once()  # cache has real data before the first SSE frame
        self._task = asyncio.create_task(self._poll_loop(), name="massive-poller")
        logger.info("Massive poller started: %d tickers, %.1fs", len(self._tickers), self._interval)

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._client = None

    async def add_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        if ticker not in self._tickers:
            self._tickers.append(ticker)  # appears on next poll

    async def remove_ticker(self, ticker: str) -> None:
        ticker = normalize_ticker(ticker)
        self._tickers = [t for t in self._tickers if t != ticker]
        self._cache.remove(ticker)

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    async def _poll_loop(self) -> None:
        while True:
            await asyncio.sleep(self._interval)
            await self._poll_once()

    async def _poll_once(self) -> None:
        if not self._tickers or not self._client:
            return
        try:
            snapshots = await asyncio.to_thread(self._fetch_snapshots)
        except Exception as e:  # 401/403/429/network — retry next interval
            logger.error("Massive poll failed: %s", e)
            return

        tracked = set(self._tickers)
        for snap in snapshots:
            parsed = parse_snapshot(snap)
            if parsed is None:
                logger.warning("Skipping unusable snapshot for %s", getattr(snap, "ticker", "?"))
                continue
            if parsed.ticker not in tracked:  # removed while the request was in flight
                continue
            self._cache.update(
                ticker=parsed.ticker,
                price=parsed.price,
                timestamp=parsed.timestamp,
                reference_price=parsed.reference_price,
            )

    def _fetch_snapshots(self) -> list[TickerSnapshot]:
        """Synchronous SDK call — run via asyncio.to_thread."""
        return self._client.get_snapshot_all(
            market_type=SnapshotMarketType.STOCKS,
            tickers=list(self._tickers),
        )
```

Behaviour notes:

- **One HTTP call per poll** for all tickers (`?tickers=AAPL,GOOGL,...`), so the free tier's 5 req/min allows a 15 s interval with one call of headroom.
- **Errors never escape the loop.** 401 (bad key), 403 (plan), 429 (rate limit) and network errors are logged; the next interval retries. The cache keeps the last good prices.
- **Removal race:** if a ticker is removed while a request is in flight, its result is dropped instead of reinserted into the cache.
- **`list(self._tickers)`** passes a copy to the worker thread, so `add_ticker` on the event loop can't mutate the list mid-request.
- **Market closed:** `last_trade.price` is the last trade (may be after-hours). Prices stop changing, `version` still bumps each poll, and SSE re-sends identical prices with `direction: "flat"`, so the UI shows no flashes. That's correct.
- **Unknown symbols** (e.g. `ZZZZ`) return no snapshot, so the ticker has no cache entry. The watchlist shows it as "—" (§17).

---

## 11. Source selection — `factory.py`

```python
"""Factory for creating market data sources."""

from __future__ import annotations

import logging
import os

from .cache import PriceCache
from .interface import MarketDataSource
from .massive_client import MassiveDataSource
from .simulator import SimulatorDataSource

logger = logging.getLogger(__name__)


def create_market_data_source(price_cache: PriceCache) -> MarketDataSource:
    """MASSIVE_API_KEY set → MassiveDataSource; otherwise SimulatorDataSource.

    MASSIVE_POLL_INTERVAL (seconds, default 15) tunes the poller for paid tiers.
    Returns an unstarted source; caller must `await source.start(tickers)`.
    """
    api_key = os.environ.get("MASSIVE_API_KEY", "").strip()
    if api_key:
        try:
            interval = float(os.environ.get("MASSIVE_POLL_INTERVAL", "15"))
        except ValueError:
            interval = 15.0
        interval = max(interval, 1.0)
        logger.info("Market data source: Massive API (poll every %.1fs)", interval)
        return MassiveDataSource(api_key=api_key, price_cache=price_cache, poll_interval=interval)

    logger.info("Market data source: GBM simulator")
    return SimulatorDataSource(price_cache=price_cache)
```

```bash
# Free tier (default)
MASSIVE_API_KEY=pk_xxx
# Paid tier: poll faster
MASSIVE_API_KEY=pk_xxx
MASSIVE_POLL_INTERVAL=3
```

---

## 12. SSE streaming — `stream.py`

### 12.1 Implementation

```python
"""SSE streaming endpoint for live price updates."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncGenerator, Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from .cache import PriceCache

logger = logging.getLogger(__name__)

PUSH_INTERVAL = 0.5  # seconds between cache checks
HEARTBEAT_INTERVAL = 15.0  # seconds of silence before a keep-alive comment
RETRY_MS = 1000  # EventSource reconnect delay


def create_stream_router(price_cache: PriceCache) -> APIRouter:
    """Build a fresh router per call (safe to call repeatedly in tests)."""
    router = APIRouter(prefix="/api/stream", tags=["streaming"])

    @router.get("/prices")
    async def stream_prices(request: Request) -> StreamingResponse:
        return StreamingResponse(
            generate_price_events(price_cache, request.is_disconnected),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    return router


async def generate_price_events(
    price_cache: PriceCache,
    is_disconnected: Callable[[], Awaitable[bool]],
    interval: float = PUSH_INTERVAL,
    heartbeat: float = HEARTBEAT_INTERVAL,
) -> AsyncGenerator[str, None]:
    """Yield SSE frames: one full snapshot whenever the cache version changes."""
    yield f"retry: {RETRY_MS}\n\n"

    last_version = -1
    last_sent = time.monotonic()
    try:
        while not await is_disconnected():
            version = price_cache.version
            if version != last_version:
                last_version = version
                prices = price_cache.get_all()
                payload = json.dumps({t: u.to_dict() for t, u in prices.items()})
                yield f"id: {version}\ndata: {payload}\n\n"
                last_sent = time.monotonic()
            elif time.monotonic() - last_sent >= heartbeat:
                yield ": keep-alive\n\n"
                last_sent = time.monotonic()
            await asyncio.sleep(interval)
    except asyncio.CancelledError:
        logger.debug("SSE stream cancelled")
        raise
```

Changes from the current version:

- **Router per call.** `create_stream_router()` builds a new `APIRouter`, so tests and app factories can call it freely.
- **`generate_price_events()` is public and takes an `is_disconnected` callable**, so tests drive it without a server (§16.2).
- **`id: <version>`** on each frame, for debugging and future resume support.
- **Heartbeat comment** (`: keep-alive`) after 15 s of silence. EventSource ignores comment lines; proxies and load balancers see traffic.
- **Removals are pushed**, because `cache.remove()` now bumps `version` and every frame is a full snapshot.
- `CancelledError` is re-raised after logging, so Starlette's shutdown sees a clean cancellation.

### 12.2 Wire format

Each frame is a **full snapshot** of every tracked ticker, sent only when the cache changed. A full snapshot is about 3 KB for 10 tickers, roughly 6 KB/s. It's simple, and a client that misses a frame loses nothing.

```
retry: 1000

id: 20
data: {"AAPL":{"ticker":"AAPL","price":190.01,"previous_price":190.0,"reference_price":190.0,"timestamp":1794840735.59,"change":0.01,"change_percent":0.0053,"day_change":0.01,"day_change_percent":0.0053,"direction":"up"},"GOOGL":{...}}

id: 40
data: {...}

: keep-alive

```

Frames use the default `message` event type, so the client uses `onmessage`.

### 12.3 Frontend consumer (reference for the Frontend agent)

```ts
// types.ts
export type Direction = "up" | "down" | "flat";
export interface PriceUpdate {
  ticker: string;
  price: number;
  previous_price: number;
  reference_price: number | null;
  timestamp: number;            // Unix seconds
  change: number;
  change_percent: number;
  day_change: number;
  day_change_percent: number;
  direction: Direction;
}
export type PriceSnapshot = Record<string, PriceUpdate>;

// usePriceStream.ts
import { useEffect, useRef, useState } from "react";

export type ConnStatus = "connected" | "reconnecting" | "disconnected";

export function usePriceStream(maxPoints = 300) {
  const [prices, setPrices] = useState<PriceSnapshot>({});
  const [status, setStatus] = useState<ConnStatus>("reconnecting");
  const history = useRef<Record<string, number[]>>({});   // sparklines, accumulated since page load

  useEffect(() => {
    const es = new EventSource("/api/stream/prices");
    es.onopen = () => setStatus("connected");
    es.onerror = () =>
      setStatus(es.readyState === EventSource.CLOSED ? "disconnected" : "reconnecting");
    es.onmessage = (e) => {
      const snap: PriceSnapshot = JSON.parse(e.data);
      for (const [t, u] of Object.entries(snap)) {
        const h = (history.current[t] ??= []);
        if (h.length === 0 || h[h.length - 1] !== u.price) h.push(u.price);
        if (h.length > maxPoints) h.shift();
      }
      setPrices(snap);
    };
    return () => es.close();
  }, [maxPoints]);

  return { prices, status, history: history.current };
}
```

Flash rule: trigger the green/red CSS class when `direction !== "flat"` **and** the price differs from the last one rendered for that ticker. Massive re-sends unchanged prices with `direction: "flat"`, so they don't flash.

### 12.4 Manual check

```bash
curl -N http://localhost:8000/api/stream/prices
```

---

## 13. Watchlist and position tracking — `tracking.py`

### 13.1 Rule

The source must track **watchlist ∪ tickers with an open position**:

- Removing `GOOGL` from the watchlist while holding 5 shares keeps GOOGL priced, so portfolio value and P&L stay live.
- Selling the last GOOGL share while it isn't on the watchlist stops tracking it.

Rather than refcounting, every mutation **reconciles** the source against the database. Reconciling is idempotent and can't drift.

```python
"""Keep the data source's ticker set equal to (watchlist ∪ open positions)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from .cache import PriceCache
from .interface import MarketDataSource
from .tickers import normalize_ticker


class PriceUnavailableError(RuntimeError):
    """No price could be obtained for a ticker in time."""


async def sync_tracked_tickers(
    source: MarketDataSource,
    watchlist: Iterable[str],
    held: Iterable[str],
) -> None:
    """Reconcile the source with the tickers the app needs prices for.

    Call after any watchlist add/remove and after any trade that opens or
    closes a position. Idempotent and cheap (set arithmetic + O(changes)).
    """
    desired = {normalize_ticker(t) for t in (*watchlist, *held)}
    current = set(source.get_tickers())
    for ticker in sorted(desired - current):
        await source.add_ticker(ticker)
    for ticker in sorted(current - desired):
        await source.remove_ticker(ticker)


async def get_price_or_wait(
    ticker: str,
    source: MarketDataSource,
    cache: PriceCache,
    timeout: float = 2.0,
    poll: float = 0.05,
) -> float:
    """Current price for `ticker`, starting to track it if necessary.

    Simulator: add_ticker seeds the cache synchronously → returns immediately.
    Massive: price arrives on the next poll; if that is beyond `timeout`,
    raises PriceUnavailableError and the caller returns a 4xx to the user.
    """
    ticker = normalize_ticker(ticker)
    price = cache.get_price(ticker)
    if price is not None:
        return price

    await source.add_ticker(ticker)
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        price = cache.get_price(ticker)
        if price is not None:
            return price
        await asyncio.sleep(poll)
    raise PriceUnavailableError(f"No price available for {ticker} yet")
```

### 13.2 Route usage (for the Backend agent)

Sketches showing where the market layer plugs in. The DB helpers (`db.get_watchlist`, `db.get_held_tickers`, ...) belong to the portfolio/watchlist work.

```python
# app/routes/watchlist.py
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.market import InvalidTickerError, normalize_ticker, sync_tracked_tickers

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])


class AddTicker(BaseModel):
    ticker: str


async def _resync(request: Request) -> None:
    await sync_tracked_tickers(
        request.app.state.market_source,
        watchlist=db.get_watchlist(),          # list[str]
        held=db.get_held_tickers(),            # tickers with quantity > 0
    )


@router.get("")
async def list_watchlist(request: Request):
    cache = request.app.state.price_cache
    out = []
    for t in db.get_watchlist():
        u = cache.get(t)
        out.append({"ticker": t, **(u.to_dict() if u else {"price": None})})
    return out


@router.post("", status_code=201)
async def add(body: AddTicker, request: Request):
    try:
        ticker = normalize_ticker(body.ticker)
    except InvalidTickerError as e:
        raise HTTPException(400, str(e))
    db.add_watchlist(ticker)                   # INSERT OR IGNORE (unique user_id, ticker)
    await _resync(request)
    u = request.app.state.price_cache.get(ticker)
    return {"ticker": ticker, "price": u.price if u else None}


@router.delete("/{ticker}", status_code=204)
async def remove(ticker: str, request: Request):
    try:
        ticker = normalize_ticker(ticker)
    except InvalidTickerError as e:
        raise HTTPException(400, str(e))
    db.remove_watchlist(ticker)
    await _resync(request)                     # stays tracked if still held
```

```python
# app/routes/portfolio.py (trade excerpt)
from app.market import (
    InvalidTickerError, PriceUnavailableError, get_price_or_wait, normalize_ticker,
    sync_tracked_tickers,
)


@router.post("/trade")
async def trade(body: TradeRequest, request: Request):
    state = request.app.state
    try:
        ticker = normalize_ticker(body.ticker)
        price = await get_price_or_wait(ticker, state.market_source, state.price_cache)
    except InvalidTickerError as e:
        raise HTTPException(400, str(e))
    except PriceUnavailableError as e:
        raise HTTPException(409, f"{e}. Add it to your watchlist and try again shortly.")

    result = db.execute_trade(ticker, body.side, body.quantity, price)   # validates cash/shares
    await sync_tracked_tickers(state.market_source, db.get_watchlist(), db.get_held_tickers())
    db.record_snapshot(portfolio_value(state.price_cache))               # PLAN: snapshot after each trade
    return result
```

The LLM chat flow runs each `trades[]` and `watchlist_changes[]` item through the **same** functions, so validation and tracking behave the same for manual and AI actions.

### 13.3 Price availability by source

| Situation | Simulator | Massive |
|---|---|---|
| Trade a watched ticker | cached, instant | cached (≤ 15 s old) |
| Trade a new ticker | `add_ticker` seeds cache, instant | waits up to 2 s, usually **409** until next poll |
| Add ticker to watchlist | price in the response | `price: null` until next poll |

---

## 14. App wiring — `app/main.py`

The cache and source are created at **import time** so routers can be included before the static mount. The lifespan only starts and stops the background task.

```python
"""FastAPI application entry point (market-data wiring only)."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.market import PriceCache, create_market_data_source, create_stream_router
from app.market.seed_prices import DEFAULT_TICKERS

logging.basicConfig(level=logging.INFO)

# One cache for the process. Created at import time so routers can be
# registered *before* the static-file catch-all mount below.
price_cache = PriceCache()
market_source = create_market_data_source(price_cache)


async def load_tracked_tickers() -> list[str]:
    """Watchlist ∪ open positions from SQLite. Placeholder until app/db exists."""
    return list(DEFAULT_TICKERS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await market_source.start(await load_tracked_tickers())
    try:
        yield
    finally:
        await market_source.stop()


app = FastAPI(title="FinAlly", lifespan=lifespan)
app.state.price_cache = price_cache
app.state.market_source = market_source

app.include_router(create_stream_router(price_cache))
# app.include_router(portfolio_router); app.include_router(watchlist_router); ...


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "tickers": len(price_cache)}


# Must be LAST: a mount at "/" matches every path not claimed above.
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

Why order matters: `app.mount("/", StaticFiles(...))` matches **every** path. Starlette tries routes in registration order, so a router included after the mount (e.g. inside the lifespan) is unreachable. Checked: with the order above, `GET /` serves `index.html`, and `/api/health` and `/api/stream/prices` both work.

`load_tracked_tickers()` becomes the following once the DB layer exists. The DB must be initialized (lazy create + seed) before this runs:

```python
async def load_tracked_tickers() -> list[str]:
    db.init()                                        # creates schema + seeds DEFAULT_TICKERS if empty
    return sorted(set(db.get_watchlist()) | set(db.get_held_tickers()))
```

Dependency helpers for route modules, if preferred over `request.app.state`:

```python
from fastapi import Request
from app.market import MarketDataSource, PriceCache

def get_price_cache(request: Request) -> PriceCache:
    return request.app.state.price_cache

def get_market_source(request: Request) -> MarketDataSource:
    return request.app.state.market_source
```

Uvicorn must run with **one worker** (`uvicorn app.main:app --host 0.0.0.0 --port 8000`). Each worker would otherwise run its own simulator with diverging prices.

---

## 15. Downstream consumers

### 15.1 Portfolio valuation

```python
def portfolio_value(cache: PriceCache) -> float:
    cash = db.get_cash()
    total = cash
    for pos in db.get_positions():                   # ticker, quantity, avg_cost
        price = cache.get_price(pos.ticker)
        total += pos.quantity * (price if price is not None else pos.avg_cost)  # fallback: cost basis
    return round(total, 2)
```

Falling back to `avg_cost` when no price is cached yet (Massive cold start) keeps the header value from collapsing to just cash.

### 15.2 Snapshot background task (every 30 s)

Started in the same lifespan, after `market_source.start(...)`:

```python
async def snapshot_loop(cache: PriceCache, interval: float = 30.0) -> None:
    while True:
        await asyncio.sleep(interval)
        try:
            db.record_snapshot(portfolio_value(cache))
        except Exception:
            logger.exception("portfolio snapshot failed")

# in lifespan:
snap_task = asyncio.create_task(snapshot_loop(price_cache), name="portfolio-snapshots")
...
snap_task.cancel()
```

### 15.3 LLM context

```python
def market_context(cache: PriceCache, tickers: list[str]) -> str:
    lines = []
    for t in tickers:
        u = cache.get(t)
        lines.append(f"{t}: ${u.price:.2f} ({u.day_change_percent:+.2f}% today)" if u else f"{t}: n/a")
    return "\n".join(lines)
```

---

## 16. Tests

Run: `cd backend && uv run --extra dev pytest -v`. The test suite in this document plus the existing simulator, model and factory tests come to **96 tests**. The existing `pytest-asyncio` auto mode means `async def test_*` needs no decorator.

### 16.1 `tests/market/test_massive.py` (rewrite)

The key change: snapshots are **real `TickerSnapshot` objects** built from API-shaped dicts. A `MagicMock` accepts any attribute name, which is exactly how bug #1 got through.

```python
"""Tests for MassiveDataSource using real SDK model objects (no MagicMock snapshots)."""

from unittest.mock import MagicMock, patch

from massive.rest.models import TickerSnapshot

from app.market.cache import PriceCache
from app.market.massive_client import MassiveDataSource, parse_snapshot

T_NS = 1_707_580_800_123_456_789  # nanoseconds


def snap(ticker="AAPL", price=190.5, prev_close=188.0, t_ns=T_NS, **extra) -> TickerSnapshot:
    d = {"ticker": ticker, "prevDay": {"c": prev_close}, "day": {"c": price}, "updated": t_ns}
    if price is not None:
        d["lastTrade"] = {"p": price, "t": t_ns}
    d.update(extra)
    return TickerSnapshot.from_dict(d)


def make_source(tickers):
    cache = PriceCache()
    src = MassiveDataSource(api_key="k", price_cache=cache, poll_interval=60)
    src._tickers = list(tickers)
    src._client = MagicMock()
    return src, cache


class TestParseSnapshot:
    def test_basic(self):
        p = parse_snapshot(snap())
        assert p.ticker == "AAPL" and p.price == 190.5 and p.reference_price == 188.0

    def test_nanoseconds_to_seconds(self):
        assert abs(parse_snapshot(snap()).timestamp - 1_707_580_800.123) < 1e-3

    def test_falls_back_to_minute_then_day_close(self):
        s = TickerSnapshot.from_dict({"ticker": "X", "min": {"c": 12.5}, "day": {"c": 11.0}})
        assert parse_snapshot(s).price == 12.5
        s = TickerSnapshot.from_dict({"ticker": "X", "day": {"c": 11.0}})
        assert parse_snapshot(s).price == 11.0

    def test_unusable_returns_none(self):
        assert parse_snapshot(TickerSnapshot.from_dict({"ticker": "X"})) is None
        assert parse_snapshot(TickerSnapshot.from_dict({"lastTrade": {"p": 1.0}})) is None

    def test_missing_prev_day(self):
        s = TickerSnapshot.from_dict({"ticker": "X", "lastTrade": {"p": 5.0}})
        assert parse_snapshot(s).reference_price is None


class TestPolling:
    async def test_poll_updates_cache_with_day_change(self):
        src, cache = make_source(["AAPL", "GOOGL"])
        with patch.object(src, "_fetch_snapshots", return_value=[snap(), snap("GOOGL", 175.0, 170.0)]):
            await src._poll_once()
        u = cache.get("AAPL")
        assert u.price == 190.5 and u.reference_price == 188.0
        assert u.day_change_percent == round((190.5 - 188) / 188 * 100, 4)
        assert cache.get_price("GOOGL") == 175.0

    async def test_bad_snapshot_skipped_others_kept(self):
        src, cache = make_source(["AAPL", "BAD"])
        bad = TickerSnapshot.from_dict({"ticker": "BAD"})
        with patch.object(src, "_fetch_snapshots", return_value=[snap(), bad]):
            await src._poll_once()
        assert "AAPL" in cache and "BAD" not in cache

    async def test_api_error_does_not_raise(self):
        src, cache = make_source(["AAPL"])
        with patch.object(src, "_fetch_snapshots", side_effect=RuntimeError("429")):
            await src._poll_once()
        assert len(cache) == 0

    async def test_ignores_ticker_removed_mid_flight(self):
        src, cache = make_source(["AAPL"])
        with patch.object(src, "_fetch_snapshots", return_value=[snap(), snap("ZZZ")]):
            await src._poll_once()
        assert "ZZZ" not in cache

    async def test_add_remove_normalizes(self):
        src, cache = make_source([])
        await src.add_ticker(" tsla ")
        assert src.get_tickers() == ["TSLA"]
        cache.update("TSLA", 1.0)
        await src.remove_ticker("tsla")
        assert src.get_tickers() == [] and "TSLA" not in cache

    async def test_start_polls_immediately_and_stop(self):
        cache = PriceCache()
        src = MassiveDataSource(api_key="k", price_cache=cache, poll_interval=60)
        with patch("app.market.massive_client.RESTClient") as rc:
            rc.return_value.get_snapshot_all.return_value = [snap()]
            await src.start(["aapl"])
            assert cache.get_price("AAPL") == 190.5
            await src.stop()
            await src.stop()  # idempotent
```

### 16.2 `tests/market/test_stream.py` (new)

```python
"""Tests for the SSE generator and router."""

import json

from fastapi import FastAPI

from app.market.cache import PriceCache
from app.market.stream import create_stream_router, generate_price_events


class Disconnect:
    """is_disconnected() stand-in: reports disconnected after n checks."""

    def __init__(self, after: int):
        self.calls, self.after = 0, after

    async def __call__(self) -> bool:
        self.calls += 1
        return self.calls > self.after


async def collect(cache, checks, **kw):
    return [f async for f in generate_price_events(cache, Disconnect(checks), interval=0, **kw)]


def data_frames(frames):
    return [json.loads(f.split("data: ", 1)[1]) for f in frames if "data: " in f]


async def test_first_frame_is_retry():
    frames = await collect(PriceCache(), 0)
    assert frames == ["retry: 1000\n\n"]


async def test_snapshot_contains_all_fields():
    cache = PriceCache()
    cache.update("AAPL", 190.0)
    cache.update("AAPL", 191.0)
    (payload,) = data_frames(await collect(cache, 1))
    a = payload["AAPL"]
    assert a["price"] == 191.0 and a["previous_price"] == 190.0 and a["direction"] == "up"
    assert a["reference_price"] == 190.0 and a["day_change"] == 1.0
    assert {"timestamp", "change", "change_percent", "day_change_percent"} <= a.keys()


async def test_frame_has_id():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    frames = await collect(cache, 1)
    assert frames[1].startswith(f"id: {cache.version}\ndata: ")


async def test_no_duplicate_when_version_unchanged():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    assert len(data_frames(await collect(cache, 5))) == 1


async def test_heartbeat_when_idle():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    frames = await collect(cache, 3, heartbeat=0)
    assert ": keep-alive\n\n" in frames


async def test_removal_is_pushed():
    cache = PriceCache()
    cache.update("AAPL", 1.0)
    cache.update("MSFT", 2.0)
    cache.remove("MSFT")
    (payload,) = data_frames(await collect(cache, 1))
    assert list(payload) == ["AAPL"]


def test_router_factory_is_reentrant():
    cache = PriceCache()
    app = FastAPI()
    app.include_router(create_stream_router(cache))
    app.include_router(create_stream_router(cache))  # separate router objects
    r1, r2 = create_stream_router(cache), create_stream_router(cache)
    assert r1 is not r2 and len(r1.routes) == 1
```

### 16.3 `tests/market/test_tracking.py` (new)

```python
"""Tests for ticker normalization and watchlist/position tracking."""

import pytest

from app.market.cache import PriceCache
from app.market.simulator import SimulatorDataSource
from app.market.tickers import InvalidTickerError, normalize_ticker
from app.market.tracking import PriceUnavailableError, get_price_or_wait, sync_tracked_tickers


@pytest.mark.parametrize("raw,expected", [(" aapl ", "AAPL"), ("brk.b", "BRK.B"), ("BF-B", "BF-B")])
def test_normalize_ok(raw, expected):
    assert normalize_ticker(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "TOOLONG", "A1", "$AAPL", "AAPL;DROP", None])
def test_normalize_rejects(raw):
    with pytest.raises(InvalidTickerError):
        normalize_ticker(raw)


async def test_sync_adds_and_removes():
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=60)
    await src.start(["AAPL", "GOOGL", "MSFT"])
    try:
        # GOOGL removed from watchlist but still held → keep; MSFT dropped; PYPL added
        await sync_tracked_tickers(src, watchlist=["AAPL", "pypl"], held=["GOOGL"])
        assert set(src.get_tickers()) == {"AAPL", "GOOGL", "PYPL"}
        assert "MSFT" not in cache and "PYPL" in cache
    finally:
        await src.stop()


async def test_get_price_or_wait_simulator_is_immediate():
    cache = PriceCache()
    src = SimulatorDataSource(cache, update_interval=60)
    await src.start([])
    try:
        price = await get_price_or_wait("pypl", src, cache, timeout=0.01)
        assert price > 0 and "PYPL" in src.get_tickers()
    finally:
        await src.stop()


async def test_get_price_or_wait_times_out():
    class NeverPrices(SimulatorDataSource):
        async def add_ticker(self, ticker):  # tracks, but no price arrives
            pass

    cache = PriceCache()
    with pytest.raises(PriceUnavailableError):
        await get_price_or_wait("ZZZ", NeverPrices(cache), cache, timeout=0.05)
```

### 16.4 `tests/market/test_cache.py` (append)

```python
class TestReferencePrice:
    def test_first_update_sets_reference(self):
        c = PriceCache()
        assert c.update("A", 100.0).reference_price == 100.0

    def test_reference_carried_forward(self):
        c = PriceCache()
        c.update("A", 100.0)
        u = c.update("A", 110.0)
        assert u.reference_price == 100.0 and u.day_change_percent == 10.0

    def test_explicit_reference_wins(self):
        c = PriceCache()
        c.update("A", 100.0)
        assert c.update("A", 101.0, reference_price=95.0).reference_price == 95.0

    def test_zero_timestamp_respected(self):
        assert PriceCache().update("A", 1.0, timestamp=0.0).timestamp == 0.0

    def test_remove_bumps_version_only_if_present(self):
        c = PriceCache()
        c.update("A", 1.0)
        v = c.version
        c.remove("A")
        assert c.version == v + 1
        c.remove("A")
        assert c.version == v + 1
```

### 16.5 Optional live smoke test (real key, not in CI)

```python
# tests/market/test_massive_live.py
import os, pytest
from app.market import PriceCache
from app.market.massive_client import MassiveDataSource

@pytest.mark.skipif(not os.environ.get("MASSIVE_API_KEY"), reason="needs MASSIVE_API_KEY")
async def test_live_snapshot():
    cache = PriceCache()
    src = MassiveDataSource(os.environ["MASSIVE_API_KEY"], cache, poll_interval=60)
    await src.start(["AAPL", "MSFT"])
    try:
        assert cache.get_price("AAPL") and cache.get("AAPL").reference_price
    finally:
        await src.stop()
```

### 16.6 E2E hooks (for `test/`)

- **Prices streaming:** read two SSE frames from `/api/stream/prices` and check at least one price changed (simulator mode).
- **Reconnection:** restart the container mid-test; the header dot goes yellow, then back to green within ~1 s of the server returning (`retry: 1000`).

---

## 17. Edge cases and error handling

| Case | Behaviour |
|---|---|
| Empty watchlist at startup | Source starts with `[]`; SSE sends `retry` then heartbeats; adding a ticker starts prices. |
| Invalid symbol (`$AAPL`, `A1`) | `normalize_ticker` → `InvalidTickerError` → **400**. |
| Well-formed but nonexistent symbol (`ZZZZ`) | Simulator: invents a price (U(50, 300)), acceptable in a simulation. Massive: no snapshot, so no cache entry; watchlist shows `price: null`; trades get **409**. |
| Duplicate add | `add_ticker` no-op; DB unique constraint; 201 with existing price. |
| Remove a held ticker from watchlist | Stays tracked via `sync_tracked_tickers` (held set). |
| Massive 401/403 | Logged every poll; cache stays empty. Fix the key or unset it to use the simulator. |
| Massive 429 | Logged; next poll retries. Lower the poll rate if it persists. |
| Massive slow response (> interval) | `_poll_loop` sleeps *after* each poll, so polls never overlap. |
| Market closed (Massive) | Last trade price; `direction: "flat"`; no flashes. |
| Simulator step raises | Logged with traceback; loop continues next tick. |
| SSE client disconnects | `is_disconnected()` ends the generator within one interval. |
| Server restart | Browser auto-reconnects after 1 s; first frame is a full snapshot. |
| Price precision | Cache rounds to cents; the simulator keeps full precision internally, so rounding doesn't accumulate. |

---

## 18. Configuration

| Variable | Default | Effect |
|---|---|---|
| `MASSIVE_API_KEY` | empty | Set → Massive poller; empty/absent → simulator |
| `MASSIVE_POLL_INTERVAL` | `15` | Seconds between Massive polls (min 1). Free tier: keep ≥ 13. |

| Constant | Value | Location |
|---|---|---|
| Simulator tick | 0.5 s | `SimulatorDataSource(update_interval)` |
| Shock probability | 0.001 / ticker / tick | `SimulatorDataSource(event_probability)` |
| SSE push check | 0.5 s | `stream.PUSH_INTERVAL` |
| SSE heartbeat | 15 s | `stream.HEARTBEAT_INTERVAL` |
| SSE reconnect | 1000 ms | `stream.RETRY_MS` |
| Trade price wait | 2 s | `get_price_or_wait(timeout)` |

---

## 19. Implementation checklist

In order; each step keeps the suite green.

1. [ ] Add `app/market/tickers.py`; use it in `SimulatorDataSource` and `MassiveDataSource`.
2. [ ] `models.py`: add `reference_price`, `day_change`, `day_change_percent`; extend `to_dict()`.
3. [ ] `cache.py`: `reference_price` param + carry-forward; `timestamp is not None`; locked `version`; `remove()` bumps version.
4. [ ] `massive_client.py`: add `parse_snapshot()` with `sip_timestamp` (ns) and `prev_day.close`; filter removed tickers; pass a ticker copy to the thread.
5. [ ] Rewrite `test_massive.py` with real `TickerSnapshot` objects.
6. [ ] `factory.py`: `MASSIVE_POLL_INTERVAL`.
7. [ ] `stream.py`: router per call, public `generate_price_events`, `id:`, heartbeat; add `test_stream.py`.
8. [ ] `seed_prices.py`: `DEFAULT_TICKERS`.
9. [ ] Add `app/market/tracking.py` + `test_tracking.py`; update `__init__.py` exports.
10. [ ] Add `app/main.py` (lifespan, router order, static mount last); swap `load_tracked_tickers()` to the DB once it exists.
11. [ ] Update `planning/archive/MASSIVE_API.md` field names (`prev_day.close`, `todays_change_percent`, ns timestamps) and `backend/CLAUDE.md` (new exports, SSE fields).
