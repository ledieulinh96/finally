"""Data models for market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["up", "down", "flat"]


def iso_utc(ts: datetime) -> str:
    """ISO-8601 UTC timestamp with millisecond precision and a ``Z`` suffix."""
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """Immutable latest-price snapshot for one ticker.

    Each cache update replaces the whole object, so readers never see a
    half-written quote. ``name`` is deliberately not part of the quote — names
    belong to the listing / watchlist metadata (see ``names.NameRegistry``).
    """

    ticker: str  # 6-char KRX short code, e.g. "005930" — always str
    price: int  # KRW, tick-aligned
    prev_price: int  # price before this update (== price on first sighting)
    session_open: int  # first price seen in this server session
    timestamp: datetime  # tz-aware UTC
    version: int  # cache version at which this quote was written

    @property
    def direction(self) -> Direction:
        if self.price > self.prev_price:
            return "up"
        if self.price < self.prev_price:
            return "down"
        return "flat"

    @property
    def change(self) -> int:
        """KRW change versus the previous update."""
        return self.price - self.prev_price

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
            "timestamp": iso_utc(self.timestamp),
        }
