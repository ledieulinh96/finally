"""KRX price rules: tick sizes, the daily ±30% limit, and ticker validation.

KOSPI, KOSDAQ and NXT share one tick table (호가가격단위). Real KRX prices are
always integers on a tick boundary, so every price written to the cache goes
through ``snap_to_tick``.
"""

from __future__ import annotations

import math
import re

# (exclusive upper bound, tick) — prices at or above the last bound use 1,000.
_TICKS: tuple[tuple[int, int], ...] = (
    (2_000, 1),
    (5_000, 5),
    (20_000, 10),
    (50_000, 50),
    (200_000, 100),
    (500_000, 500),
)
_TOP_TICK = 1_000

PRICE_LIMIT = 0.30  # ±30% of the base price

TICKER_RE = re.compile(r"^[0-9A-Z]{6}$")


def tick_size(price: float) -> int:
    """Tick size in KRW for a price level."""
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return _TOP_TICK


def snap_to_tick(price: float) -> int:
    """Round a float price to the nearest valid KRX tick (minimum one tick)."""
    if not math.isfinite(price) or price <= 0:
        raise ValueError(f"price must be a positive finite number, got {price!r}")
    tick = tick_size(price)
    # Rounding may land exactly on a band boundary (199,960 -> 200,000). Every
    # boundary is a multiple of the next band's tick, so the result stays valid.
    return max(tick, int(round(price / tick)) * tick)


def snap_down(price: float) -> int:
    """Largest valid tick price <= ``price``."""
    tick = tick_size(price)
    return max(tick, int(math.floor(price / tick)) * tick)


def snap_up(price: float) -> int:
    """Smallest valid tick price >= ``price``."""
    tick = tick_size(price)
    return int(math.ceil(price / tick)) * tick  # boundaries are valid in both bands


def limit_band(base_price: int) -> tuple[int, int]:
    """(lower, upper) tick-aligned daily limit prices around ``base_price``.

    The upper bound is snapped down and the lower bound up, so a published price
    can never leave the band (상한가 / 하한가).
    """
    return snap_up(base_price * (1 - PRICE_LIMIT)), snap_down(base_price * (1 + PRICE_LIMIT))


def normalize_ticker(ticker: str) -> str:
    """Strip/upper-case a ticker and validate it as a 6-character KRX short code.

    Raises ValueError for anything else. Tickers are always strings — leading
    zeros matter (``005930``).
    """
    if not isinstance(ticker, str):
        raise ValueError(f"ticker must be a string, got {type(ticker).__name__}")
    t = ticker.strip().upper()
    for suffix in (".KS", ".KQ"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
    if not TICKER_RE.match(t):
        raise ValueError(f"invalid KRX ticker {ticker!r}: expected 6 characters [0-9A-Z]")
    return t


def is_valid_ticker(ticker: str) -> bool:
    try:
        normalize_ticker(ticker)
    except ValueError:
        return False
    return True
