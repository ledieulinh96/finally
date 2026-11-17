"""yfinance poller — optional real (delayed) KOSPI/KOSDAQ prices.

Enabled with ``USE_YFINANCE=true``. Yahoo data for KRX is ~20 minutes delayed,
unofficial and rate-limited without notice, so this source:

  - resolves ``005930`` → ``005930.KS`` via the bundled listing, falling back to
    probing ``.KS`` then ``.KQ`` (PLAN Q1) and caching the result;
  - polls all symbols in ONE batched ``yf.download`` call per cycle, in a worker
    thread so the event loop is never blocked;
  - skips missing/NaN symbols and keeps their last cached price;
  - backs off exponentially on errors (15 s → 5 min) and reports
    ``status == "degraded"`` after 3 consecutive failures;
  - only writes to the cache when a price actually changes (no flat spam
    between polls — the SSE stream sends keepalives instead).

``session_open`` is the first price received after server start (PLAN §6); it
is not Yahoo's official day open. Outside KRX hours prices are frozen at the
last close — see ``market_hours.market_session``.

All network access goes through a ``QuoteFetcher`` so tests inject a fake.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Iterable
from typing import Protocol

from .base import MarketDataSource, SourceStatus
from .cache import PriceCache
from .listing import lookup
from .names import NameRegistry
from .ticks import normalize_ticker, snap_to_tick

logger = logging.getLogger(__name__)

MAX_BACKOFF = 300.0
DEGRADED_AFTER = 3


class QuoteFetcher(Protocol):
    """Synchronous network boundary (called via asyncio.to_thread)."""

    def fetch_batch(self, symbols: list[str]) -> dict[str, float]:
        """Latest price per symbol; symbols with no data are omitted."""

    def probe(self, symbol: str) -> float | None:
        """Last price for one symbol, or None if Yahoo does not know it."""

    def short_name(self, symbol: str) -> str | None:
        """Yahoo shortName (terse, sometimes Korean). Slow — never in the poll loop."""


def _valid_price(value: object) -> float | None:
    try:
        price = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return price if math.isfinite(price) and price > 0 else None


class YahooFetcher:
    """Real QuoteFetcher backed by the ``yfinance`` package (imported lazily)."""

    def fetch_batch(self, symbols: list[str]) -> dict[str, float]:
        if not symbols:
            return {}
        import pandas as pd
        import yfinance as yf

        df = yf.download(
            tickers=symbols,
            period="1d",
            interval="1m",
            group_by="ticker",
            progress=False,
            threads=False,
            auto_adjust=False,
        )
        result: dict[str, float] = {}
        if df is None or df.empty:
            return result
        multi = isinstance(df.columns, pd.MultiIndex)
        for symbol in symbols:
            try:
                frame = df[symbol] if multi else df
                closes = frame["Close"].dropna()
            except KeyError:
                continue
            if len(closes):
                price = _valid_price(closes.iloc[-1])
                if price is not None:
                    result[symbol] = price
        return result

    def probe(self, symbol: str) -> float | None:
        import yfinance as yf

        try:
            return _valid_price(yf.Ticker(symbol).fast_info["last_price"])
        except Exception:  # unknown symbols raise a variety of errors
            return None

    def short_name(self, symbol: str) -> str | None:
        import yfinance as yf

        try:
            name = yf.Ticker(symbol).info.get("shortName")
        except Exception:
            return None
        return name.strip() if isinstance(name, str) and name.strip() else None


class YFinanceSource(MarketDataSource):
    name = "yfinance"

    def __init__(
        self,
        cache: PriceCache,
        poll_interval: float = 15.0,
        fetcher: QuoteFetcher | None = None,
        names: NameRegistry | None = None,
    ) -> None:
        super().__init__(cache)
        self._interval = poll_interval
        self._fetcher: QuoteFetcher = fetcher or YahooFetcher()
        self._names = names
        self._symbols: dict[str, str] = {}  # "005930" -> "005930.KS"
        self._resolved: dict[str, str] = {}  # memo of successful resolutions
        self._task: asyncio.Task | None = None
        self._failures = 0
        self._running = False

    # --- MarketDataSource ---

    async def start(self, tickers: Iterable[str]) -> None:
        for raw in tickers:
            try:
                t = normalize_ticker(raw)
            except ValueError:
                logger.warning("yfinance: ignoring invalid ticker %r", raw)
                continue
            symbol = await asyncio.to_thread(self._resolve_symbol, t)
            if symbol:
                self._symbols[t] = symbol
            else:
                logger.warning("yfinance: cannot resolve %s; not tracked", t)
        await self.poll_once()  # initial prices before the first SSE frame
        self._running = True
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="yfinance-poller")
        logger.info(
            "yfinance poller started: %d symbols, %.0fs interval",
            len(self._symbols),
            self._interval,
        )

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> bool:
        try:
            t = normalize_ticker(ticker)
        except ValueError:
            return False
        if t in self._symbols:
            return True
        symbol = await asyncio.to_thread(self._resolve_symbol, t)
        if not symbol:
            return False
        self._symbols[t] = symbol
        try:
            prices = await asyncio.to_thread(self._fetcher.fetch_batch, [symbol])
            self._apply(prices)
        except Exception:
            logger.exception("yfinance: first price for %s failed; will retry on next poll", t)
        return True

    async def remove_ticker(self, ticker: str) -> None:
        try:
            t = normalize_ticker(ticker)
        except ValueError:
            return
        self._symbols.pop(t, None)
        self.cache.remove(t)

    @property
    def tickers(self) -> frozenset[str]:
        return frozenset(self._symbols)

    @property
    def status(self) -> SourceStatus:
        if not self._running:
            return "stopped"
        return "degraded" if self._failures >= DEGRADED_AFTER else "ok"

    def symbol_for(self, ticker: str) -> str | None:
        return self._symbols.get(ticker)

    # --- Polling ---

    async def poll_once(self) -> bool:
        """One batched poll. Returns True on success (even if some symbols were missing)."""
        if not self._symbols:
            return True
        try:
            prices = await asyncio.to_thread(
                self._fetcher.fetch_batch, list(self._symbols.values())
            )
        except Exception as exc:
            self._failures += 1
            logger.warning("yfinance poll failed (%d in a row): %s", self._failures, exc)
            return False
        self._failures = 0
        self._apply(prices)
        return True

    def next_delay(self) -> float:
        if self._failures == 0:
            return self._interval
        return min(self._interval * 2**self._failures, MAX_BACKOFF)

    def _apply(self, prices: dict[str, float]) -> None:
        for ticker, symbol in list(self._symbols.items()):
            raw = _valid_price(prices.get(symbol))
            if raw is None:
                continue  # missing / NaN: keep the last cached price
            price = snap_to_tick(raw)
            if price != self.cache.price(ticker):
                self.cache.update(ticker, price)

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(self.next_delay())
            await self.poll_once()

    def _resolve_symbol(self, ticker: str) -> str | None:
        """Listing → ``.KS`` probe → ``.KQ`` probe. Successful resolutions are memoized."""
        if ticker in self._resolved:
            return self._resolved[ticker]
        entry = lookup(ticker)
        symbol: str | None = None
        if entry:
            symbol = entry.yf_symbol
        else:
            for suffix in (".KS", ".KQ"):
                if self._fetcher.probe(ticker + suffix) is not None:
                    symbol = ticker + suffix
                    break
            if symbol and self._names is not None and not self._names.known(ticker):
                self._names.set(ticker, self._fetcher.short_name(symbol))
        if symbol:  # don't memoize misses: a network blip must not ban a ticker forever
            self._resolved[ticker] = symbol
        return symbol
