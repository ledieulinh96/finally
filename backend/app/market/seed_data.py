"""Default KOSPI universe: seed prices, names and simulator parameters.

See planning/MARKET_SIMULATOR.md §3. σ is annualized volatility; β_m / β_s are
loadings on the market and sector factors (β_e = sqrt(1 - β_m² - β_s²)).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SeedParams:
    name: str
    seed_price: int
    sector: str
    sigma: float
    beta_m: float
    beta_s: float
    mu: float = 0.05


SEED_PARAMS: dict[str, SeedParams] = {
    "005930": SeedParams("Samsung Electronics", 75_000, "semis", 0.30, 0.55, 0.65),
    "000660": SeedParams("SK Hynix", 180_000, "semis", 0.45, 0.50, 0.70),
    "035420": SeedParams("NAVER", 200_000, "internet", 0.35, 0.45, 0.60),
    "035720": SeedParams("Kakao", 40_000, "internet", 0.40, 0.45, 0.60),
    "005380": SeedParams("Hyundai Motor", 230_000, "autos", 0.30, 0.50, 0.65),
    "373220": SeedParams("LG Energy Solution", 350_000, "battery", 0.45, 0.45, 0.65),
    "207940": SeedParams("Samsung Biologics", 800_000, "bio", 0.30, 0.35, 0.60),
    "068270": SeedParams("Celltrion", 200_000, "bio", 0.35, 0.35, 0.60),
    "000270": SeedParams("Kia", 100_000, "autos", 0.30, 0.50, 0.65),
    "005490": SeedParams("POSCO Holdings", 300_000, "battery", 0.40, 0.50, 0.55),
}

# Default watchlist, in PLAN.md §7 order.
DEFAULT_TICKERS: tuple[str, ...] = tuple(SEED_PARAMS)

# Parameters for tickers added at runtime that are not in SEED_PARAMS:
# their own sector ("other"), sharing only the market factor.
DEFAULT_SIGMA = 0.40
DEFAULT_BETA_M = 0.45
DEFAULT_SECTOR = "other"
