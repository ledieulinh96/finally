"""Select the market data source from environment configuration."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .base import MarketDataSource
from .cache import PriceCache

logger = logging.getLogger(__name__)


def _float(env: Mapping[str, str], key: str, default: float) -> float:
    try:
        return float(env[key]) if env.get(key, "").strip() else default
    except ValueError:
        logger.warning("Invalid %s=%r, using %s", key, env[key], default)
        return default


def create_source(cache: PriceCache, env: Mapping[str, str] | None = None) -> MarketDataSource:
    """USE_YFINANCE=true -> YFinanceSource, otherwise SimulatorSource. Returns an unstarted source."""
    env = os.environ if env is None else env
    if env.get("USE_YFINANCE", "").strip().lower() == "true":
        from .yfinance_source import YFinanceSource

        logger.info("Market data source: yfinance")
        return YFinanceSource(cache, poll_interval=15.0)

    from .simulator import SimulatorSource

    seed_raw = env.get("SIM_SEED", "").strip()
    logger.info("Market data source: simulator")
    return SimulatorSource(
        cache,
        update_interval=_float(env, "SIM_UPDATE_INTERVAL", 0.5),
        time_scale=_float(env, "SIM_TIME_SCALE", 200.0),
        seed=int(seed_raw) if seed_raw.lstrip("-").isdigit() else None,
        event_rate_per_min=_float(env, "SIM_EVENT_RATE", 0.1),
    )
