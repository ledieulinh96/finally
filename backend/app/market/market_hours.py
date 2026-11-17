"""KRX session clock (KST, UTC+9).

Used to tell the UI *why* real (yfinance) prices are flat: outside the regular
session the feed returns the last close indefinitely. The simulator ignores the
clock and trades 24/7. Exchange holidays are not modeled — a holiday reports
``regular`` during trading hours.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta, timezone
from typing import Literal

KST = timezone(timedelta(hours=9), name="KST")

MarketSession = Literal["pre_open", "regular", "closing_auction", "after_hours", "closed"]

_PRE_OPEN = time(8, 30)  # opening single-price auction
_OPEN = time(9, 0)
_CLOSING_AUCTION = time(15, 20)
_CLOSE = time(15, 30)
_AFTER_END = time(20, 0)  # KRX after-market (from 2026-09-14) / NXT


def market_session(now: datetime | None = None) -> MarketSession:
    """Current KRX session for a tz-aware instant (default: now)."""
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    kst = now.astimezone(KST)
    if kst.weekday() >= 5:
        return "closed"
    t = kst.time()
    if _PRE_OPEN <= t < _OPEN:
        return "pre_open"
    if _OPEN <= t < _CLOSING_AUCTION:
        return "regular"
    if _CLOSING_AUCTION <= t < _CLOSE:
        return "closing_auction"
    if _CLOSE <= t < _AFTER_END:
        return "after_hours"
    return "closed"


def is_market_open(now: datetime | None = None) -> bool:
    """True during the regular session including the closing auction."""
    return market_session(now) in ("regular", "closing_auction")
