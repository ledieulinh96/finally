"""Data models for market data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

Direction = Literal["up", "down", "flat"]


@dataclass(frozen=True, slots=True)
class PriceQuote:
    """Immutable latest price for one ticker. Prices are integer KRW."""

    ticker: str  # 6-char KRX code, e.g. "005930" — always str
    price: int
    prev_price: int  # price before this update
    session_open: int  # first price seen this server session
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
    def session_change_pct(self) -> float:
        if self.session_open == 0:
            return 0.0
        return round((self.price - self.session_open) / self.session_open * 100, 2)

    def to_event(self, name: str) -> dict:
        """Exact SSE payload shape from PLAN.md section 6."""
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
