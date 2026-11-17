"""Keeps the source's tracked set equal to watchlist ∪ open positions.

A stock you hold must keep a live price even after it leaves the watchlist,
otherwise portfolio value and P&L freeze. The API layer computes the wanted set
from the database and calls ``sync`` after any watchlist change or a trade that
opens/closes a position. The tracker itself never touches the database.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable

from .base import MarketDataSource
from .ticks import normalize_ticker


class TickerTracker:
    def __init__(self, source: MarketDataSource) -> None:
        self.source = source
        self._lock = asyncio.Lock()

    async def sync(self, watchlist: Iterable[str], positions: Iterable[str] = ()) -> set[str]:
        """Add missing tickers and drop unwanted ones.

        Returns the wanted tickers the source could NOT price (e.g. unknown to
        yfinance), so the caller can report them.
        """
        wanted = {normalize_ticker(t) for t in (*watchlist, *positions)}
        failed: set[str] = set()
        async with self._lock:
            for t in sorted(wanted - self.source.tickers):
                if not await self.source.add_ticker(t):
                    failed.add(t)
            for t in sorted(self.source.tickers - wanted):
                await self.source.remove_ticker(t)
        return failed

    async def ensure(self, ticker: str) -> bool:
        """Track one ticker (e.g. before buying something not on the watchlist)."""
        async with self._lock:
            return await self.source.add_ticker(normalize_ticker(ticker))
