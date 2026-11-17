"""Abstract market data source interface."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .cache import PriceCache


class MarketDataSource(ABC):
    """Produces prices for a dynamic set of tickers and writes them to a PriceCache.

    Contract: prices written are int, > 0 and tick-aligned; loop errors are logged and
    swallowed; no DB access; stop() and remove_ticker() are idempotent.
    """

    def __init__(self, cache: PriceCache) -> None:
        self.cache = cache

    @abstractmethod
    async def start(self, tickers: set[str]) -> None:
        """Begin producing prices; seed the cache for each ticker where possible."""

    @abstractmethod
    async def stop(self) -> None:
        """Cancel background work. Idempotent."""

    @abstractmethod
    async def add_ticker(self, ticker: str) -> bool:
        """Track `ticker`. False if the source cannot price it. Idempotent."""

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
