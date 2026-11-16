"""Seed universe, simulator parameters and ticker validation."""

from __future__ import annotations

import math
import random
import re
import zlib
from dataclasses import dataclass

from .ticks import snap_to_tick

_TICKER_RE = re.compile(r"[0-9A-Z]{6}")


class InvalidTickerError(ValueError):
    """Raised for a malformed KRX short code."""


def normalize_ticker(raw: str) -> str:
    """Strip + upper-case + validate a 6-char KRX short code (kept as str)."""
    ticker = (raw or "").strip().upper()
    if not _TICKER_RE.fullmatch(ticker):
        raise InvalidTickerError(f"Invalid ticker: {raw!r}")
    return ticker


@dataclass(frozen=True)
class SeedParams:
    seed_price: int
    sector: str
    sigma: float  # annualised volatility
    beta_m: float  # loading on the market factor
    beta_s: float  # loading on the sector factor
    mu: float = 0.05

    @property
    def beta_e(self) -> float:
        return math.sqrt(max(0.0, 1.0 - self.beta_m**2 - self.beta_s**2))


SEED_PARAMS: dict[str, SeedParams] = {
    "005930": SeedParams(75_000, "semis", 0.30, 0.55, 0.65),
    "000660": SeedParams(180_000, "semis", 0.45, 0.50, 0.70),
    "035420": SeedParams(200_000, "internet", 0.35, 0.45, 0.60),
    "035720": SeedParams(40_000, "internet", 0.40, 0.45, 0.60),
    "005380": SeedParams(230_000, "autos", 0.30, 0.50, 0.65),
    "000270": SeedParams(100_000, "autos", 0.30, 0.50, 0.65),
    "373220": SeedParams(350_000, "battery", 0.45, 0.45, 0.65),
    "005490": SeedParams(300_000, "battery", 0.40, 0.50, 0.55),
    "207940": SeedParams(800_000, "bio", 0.30, 0.35, 0.60),
    "068270": SeedParams(200_000, "bio", 0.35, 0.35, 0.60),
}

# Default watchlist in display order (PLAN section 7).
DEFAULT_TICKERS: list[str] = [
    "005930", "000660", "035420", "035720", "005380",
    "373220", "207940", "068270", "000270", "005490",
]  # fmt: skip

OTHER_SIGMA = 0.40
OTHER_BETA_M = 0.45


def params_for(ticker: str) -> SeedParams:
    """Parameters for a ticker; unknown tickers get a deterministic pseudo seed price."""
    if ticker in SEED_PARAMS:
        return SEED_PARAMS[ticker]
    rng = random.Random(zlib.crc32(ticker.encode()))  # crc32: stable across restarts
    price = snap_to_tick(10 ** rng.uniform(3.7, 5.7))
    return SeedParams(price, "other", OTHER_SIGMA, OTHER_BETA_M, 0.0)
