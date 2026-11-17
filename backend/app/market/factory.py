"""Select and build the market data source from environment settings."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace

from .base import MarketDataSource
from .cache import PriceCache
from .names import NameRegistry

logger = logging.getLogger(__name__)

_TRUE = {"1", "true", "yes", "on"}


def _env_float(env: Mapping[str, str], key: str, default: float) -> float:
    raw = env.get(key, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring invalid %s=%r; using %s", key, raw, default)
        return default


@dataclass(frozen=True, slots=True)
class MarketSettings:
    use_yfinance: bool = False
    yfinance_poll_interval: float = 15.0
    sim_seed: int | None = None
    sim_time_scale: float = 200.0
    sim_event_rate: float = 0.1  # events per ticker per minute
    sim_update_interval: float = 0.5

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> MarketSettings:
        env = os.environ if env is None else env
        seed_raw = env.get("SIM_SEED", "").strip()
        try:
            seed = int(seed_raw) if seed_raw else None
        except ValueError:
            logger.warning("Ignoring invalid SIM_SEED=%r", seed_raw)
            seed = None
        settings = cls(
            use_yfinance=env.get("USE_YFINANCE", "").strip().lower() in _TRUE,
            yfinance_poll_interval=_env_float(env, "YFINANCE_POLL_INTERVAL", 15.0),
            sim_seed=seed,
            sim_time_scale=_env_float(env, "SIM_TIME_SCALE", 200.0),
            sim_event_rate=_env_float(env, "SIM_EVENT_RATE", 0.1),
            sim_update_interval=_env_float(env, "SIM_UPDATE_INTERVAL", 0.5),
        )
        # Fall back to defaults for values the sources would reject.
        defaults = cls()
        if settings.sim_time_scale <= 0:
            settings = replace(settings, sim_time_scale=defaults.sim_time_scale)
        if settings.sim_update_interval <= 0:
            settings = replace(settings, sim_update_interval=defaults.sim_update_interval)
        if settings.sim_event_rate < 0:
            settings = replace(settings, sim_event_rate=defaults.sim_event_rate)
        if settings.yfinance_poll_interval <= 0:
            settings = replace(settings, yfinance_poll_interval=defaults.yfinance_poll_interval)
        return settings


def create_market_data_source(
    cache: PriceCache,
    settings: MarketSettings | None = None,
    names: NameRegistry | None = None,
) -> MarketDataSource:
    """Return an unstarted source. Caller must ``await source.start(tickers)``.

    ``USE_YFINANCE=true`` → YFinanceSource (yfinance imported lazily, only when
    actually polling); otherwise the simulator.
    """
    settings = settings or MarketSettings.from_env()
    if settings.use_yfinance:
        from .yfinance_source import YFinanceSource

        logger.info("Market data source: yfinance (delayed KRX prices)")
        return YFinanceSource(cache, poll_interval=settings.yfinance_poll_interval, names=names)

    from .simulator import SimulatorSource

    logger.info("Market data source: simulator")
    return SimulatorSource(
        cache,
        update_interval=settings.sim_update_interval,
        time_scale=settings.sim_time_scale,
        seed=settings.sim_seed,
        event_rate_per_min=settings.sim_event_rate,
    )
