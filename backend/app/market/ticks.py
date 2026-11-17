"""KRX tick-size table and price snapping (KOSPI/KOSDAQ/NXT share one table)."""

from __future__ import annotations

import math

_TICKS = ((2_000, 1), (5_000, 5), (20_000, 10), (50_000, 50), (200_000, 100), (500_000, 500))
_TOP_TICK = 1_000


def tick_size(price: float) -> int:
    for upper, tick in _TICKS:
        if price < upper:
            return tick
    return _TOP_TICK


def snap_to_tick(price: float) -> int:
    """Round to the nearest valid tick (minimum one tick)."""
    t = tick_size(price)
    return max(t, int(round(price / t)) * t)


def snap_down(price: float) -> int:
    """Largest valid tick-aligned price <= price (minimum one tick)."""
    t = tick_size(price)
    return max(t, math.floor(price / t) * t)


def snap_up(price: float) -> int:
    """Smallest valid tick-aligned price >= price."""
    t = tick_size(price)
    return max(t, math.ceil(price / t) * t)
