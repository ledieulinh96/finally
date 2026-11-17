"""Tracked tickers = watchlist ∪ open positions (the only code that decides this)."""

from __future__ import annotations

from collections.abc import Callable

from .base import MarketDataSource


class PriceUnavailableError(RuntimeError):
    """No price could be obtained for a ticker."""


class TickerTracker:
    def __init__(
        self,
        source: MarketDataSource,
        watchlist: Callable[[], set[str]],
        positions: Callable[[], set[str]],
    ) -> None:
        self.source = source
        self._watchlist = watchlist
        self._positions = positions

    def wanted(self) -> set[str]:
        return set(self._watchlist()) | set(self._positions())

    async def sync(self) -> set[str]:
        """Make the source track exactly `wanted()`. Returns tickers it could not price."""
        wanted = self.wanted()
        failed: set[str] = set()
        for t in sorted(wanted - self.source.tickers):
            if not await self.source.add_ticker(t):
                failed.add(t)
        for t in sorted(self.source.tickers - wanted):
            await self.source.remove_ticker(t)
        return failed

    async def price_for_trade(self, ticker: str) -> int:
        """Cached price, adding the ticker to the source first if needed. Never returns 0."""
        cache = self.source.cache
        price = cache.price(ticker)
        if price is None:
            await self.source.add_ticker(ticker)
            price = cache.price(ticker)
        if price is None:
            raise PriceUnavailableError("No price available")
        return price
