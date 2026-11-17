"""Abstract interface for market data sources."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Literal

from .cache import PriceCache

SourceStatus = Literal["ok", "degraded", "stopped"]


class MarketDataSource(ABC):
    """Produces prices for a dynamic set of tickers and writes them to a PriceCache.

    Downstream code never asks a source for prices — it reads the cache.

    Contract every implementation follows:
      - prices written to the cache are ``int`` KRW, > 0 and tick-aligned;
      - ``start`` / ``add_ticker`` write a first price before returning, so the
        first SSE frame and the first REST call are never empty;
      - errors inside the background loop are logged and swallowed — the loop
        never dies; repeated failures flip ``status`` to ``"degraded"``;
      - no database access (the API layer owns persistence).

    Lifecycle::

        source = create_market_data_source(cache)
        await source.start({"005930", "000660"})
        await source.add_ticker("035420")     # -> True / False
        await source.remove_ticker("000660")
        await source.stop()
    """

    name: str = "abstract"

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: Iterable[str]) -> None:
        """Begin producing prices for ``tickers`` and start the background task."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel background work and release resources. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> bool:
        """Start tracking ``ticker``. Returns False if the source cannot price it.

        Idempotent: adding an already-tracked ticker returns True.
        """

    @abstractmethod
    async def remove_ticker(self, ticker: str) -> None:
        """Stop tracking ``ticker`` and drop it from the cache. Idempotent."""

    @property
    @abstractmethod
    def tickers(self) -> frozenset[str]:
        """Currently tracked tickers."""

    @property
    def status(self) -> SourceStatus:
        """'ok' | 'degraded' | 'stopped' — surfaced by GET /api/health."""
        return "ok"
