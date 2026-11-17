"""yfinance-backed source: polls ~15-20 min delayed KRX prices (opt-in)."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Callable, Iterable

from .base import MarketDataSource
from .cache import PriceCache
from .listing import ListingEntry, load_listing, yfinance_suffix
from .seed import normalize_ticker
from .ticks import snap_to_tick

logger = logging.getLogger(__name__)

MAX_BACKOFF = 300.0
DEGRADED_AFTER = 3

LastPriceFn = Callable[[str], float | None]
BatchFn = Callable[[list[str]], dict[str, float]]


def _valid_price(value: object) -> float | None:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) and f > 0 else None


def parse_download(df, symbols: Iterable[str]) -> dict[str, float]:
    """Last non-NaN Close per symbol from a yf.download frame. Missing symbols are omitted."""
    out: dict[str, float] = {}
    if df is None or getattr(df, "empty", True):
        return out
    multi = getattr(df.columns, "nlevels", 1) > 1
    for symbol in symbols:
        try:
            close = df[symbol]["Close"] if multi else df["Close"]
        except KeyError:
            continue
        close = close.dropna()
        if close.empty:
            continue
        price = _valid_price(close.iloc[-1])
        if price is not None:
            out[symbol] = price
    return out


def fetch_last_price(symbol: str) -> float | None:
    """Blocking single-symbol lookup (used when adding a ticker)."""
    import yfinance as yf

    try:
        return _valid_price(yf.Ticker(symbol).fast_info["last_price"])
    except Exception:
        return None


def fetch_batch(symbols: list[str]) -> dict[str, float]:
    """Blocking batch poll: one yf.download for all symbols."""
    if not symbols:
        return {}
    import yfinance as yf

    df = yf.download(
        tickers=symbols, period="1d", interval="1m", group_by="ticker",
        progress=False, threads=False, auto_adjust=False,
    )  # fmt: skip
    return parse_download(df, symbols)


class YFinanceSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        poll_interval: float = 15.0,
        listing: dict[str, ListingEntry] | None = None,
        last_price_fn: LastPriceFn = fetch_last_price,
        batch_fn: BatchFn = fetch_batch,
    ) -> None:
        super().__init__(cache)
        self._interval = poll_interval
        self._listing = listing if listing is not None else load_listing()
        self._last_price = last_price_fn
        self._batch = batch_fn
        self._symbols: dict[str, str] = {}  # "005930" -> "005930.KS"
        self._task: asyncio.Task | None = None
        self._failures = 0
        self._running = False

    # ---- mapping ---------------------------------------------------------------

    def resolve_symbol(self, ticker: str) -> tuple[str, float | None] | None:
        """(yfinance symbol, last price if probed). Blocking. None if unknown.

        Listing says which exchange; otherwise probe .KS then .KQ (PLAN Q1).
        """
        entry = self._listing.get(ticker)
        if entry:
            symbol = ticker + yfinance_suffix(entry.market)
            return symbol, self._last_price(symbol)
        for suffix in (".KS", ".KQ"):
            symbol = ticker + suffix
            price = self._last_price(symbol)
            if price is not None:
                return symbol, price
        return None

    # ---- lifecycle -------------------------------------------------------------

    async def start(self, tickers: set[str]) -> None:
        self._running = True
        for t in sorted(tickers):
            await self.add_ticker(t)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="yfinance-poller")

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
            ticker = normalize_ticker(ticker)
        except ValueError:
            return False
        if ticker in self._symbols:
            return True
        try:
            resolved = await asyncio.to_thread(self.resolve_symbol, ticker)
        except Exception:
            logger.exception("Symbol resolution failed for %s", ticker)
            return False
        if resolved is None:
            return False
        symbol, price = resolved
        self._symbols[ticker] = symbol
        if price is not None:
            self.cache.update(ticker, snap_to_tick(price))
        return True

    async def remove_ticker(self, ticker: str) -> None:
        try:
            ticker = normalize_ticker(ticker)
        except ValueError:
            return
        self._symbols.pop(ticker, None)
        self.cache.remove(ticker)

    @property
    def tickers(self) -> frozenset[str]:
        return frozenset(self._symbols)

    @property
    def status(self) -> str:
        if not self._running:
            return "stopped"
        return "degraded" if self._failures >= DEGRADED_AFTER else "ok"

    # ---- polling ---------------------------------------------------------------

    async def poll_once(self) -> bool:
        """One poll cycle. Returns True on success; failures are logged, never raised."""
        symbols = dict(self._symbols)
        if not symbols:
            return True
        try:
            prices = await asyncio.to_thread(self._batch, list(symbols.values()))
        except Exception:
            logger.exception("yfinance poll failed")
            self._failures += 1
            return False
        self._failures = 0
        for ticker, symbol in symbols.items():
            if ticker not in self._symbols:  # removed while in flight
                continue
            price = _valid_price(prices.get(symbol))
            if price is None:
                continue  # keep last known price
            snapped = snap_to_tick(price)
            if snapped != self.cache.price(ticker):
                self.cache.update(ticker, snapped)
        return True

    def next_delay(self) -> float:
        if self._failures == 0:
            return self._interval
        return min(self._interval * 2**self._failures, MAX_BACKOFF)

    async def _run(self) -> None:
        while True:
            await self.poll_once()
            await asyncio.sleep(self.next_delay())
