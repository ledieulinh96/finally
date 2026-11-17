"""KRX market simulator — the default price source.

Correlated GBM (market + sector factor model) with Poisson jump events, a weak
Ornstein–Uhlenbeck pull toward the seed price, KRX tick snapping and the ±30%
daily price limit. Design: planning/MARKET_SIMULATOR.md.

Per step (Δt wall-clock seconds), for each ticker i, on log-price x_i::

    dx = (μ − σ²/2)·Δτ + σ·√Δτ·(β_m·Z_m + β_s·Z_sector + β_e·ε_i)   # GBM, correlated
         − κ·(x − x̄)·Δt                                          # mean reversion
         + J                                                      # rare 2–5% jump

    Δτ = Δt · time_scale / SECONDS_PER_TRADING_YEAR

The internal price exp(x) stays a float; only the published price is snapped.
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time
import zlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from .base import MarketDataSource, SourceStatus
from .cache import PriceCache
from .seed_data import DEFAULT_BETA_M, DEFAULT_SECTOR, DEFAULT_SIGMA, SEED_PARAMS
from .ticks import PRICE_LIMIT, limit_band, normalize_ticker, snap_to_tick

logger = logging.getLogger(__name__)

SECONDS_PER_TRADING_YEAR = 252 * 6.5 * 3600  # 5,896,800
STATIONARY_LOG_STD = 0.15  # OU band: ~±15% (1σ) around the seed price
JUMP_MIN, JUMP_MAX = 0.02, 0.05
CONTAGION_PROB = 0.3
CONTAGION_FRACTION = 0.4


@dataclass(slots=True)
class TickerState:
    ticker: str
    sector: str
    mu: float
    sigma: float
    beta_m: float
    beta_s: float
    beta_e: float
    kappa: float
    x: float  # log of the internal (unsnapped) price
    x_bar: float  # log of the seed price — the OU anchor
    session_open: int
    lower: int  # daily limit band, tick-aligned
    upper: int

    @property
    def internal_price(self) -> float:
        return math.exp(self.x)


def stable_seed_price(ticker: str) -> int:
    """Deterministic pseudo-price (~₩5,000–₩500,000) for an unknown ticker.

    Uses crc32, not Python's salted hash(), so it is stable across restarts.
    """
    rng = random.Random(zlib.crc32(ticker.encode("ascii")))
    return snap_to_tick(10 ** rng.uniform(3.7, 5.7))


class SimulatorSource(MarketDataSource):
    """MarketDataSource backed by the in-process KRX simulator.

    ``step()`` is public and synchronous so tests can drive it without asyncio.
    """

    name = "simulator"

    def __init__(
        self,
        cache: PriceCache,
        update_interval: float = 0.5,
        time_scale: float = 200.0,
        seed: int | None = None,
        event_rate_per_min: float = 0.1,
        mean_reversion: bool = True,
    ) -> None:
        super().__init__(cache)
        if update_interval <= 0:
            raise ValueError("update_interval must be > 0")
        if time_scale <= 0:
            raise ValueError("time_scale must be > 0")
        if event_rate_per_min < 0:
            raise ValueError("event_rate_per_min must be >= 0")
        self._dt = update_interval
        self._time_scale = time_scale
        self._dtau = update_interval * time_scale / SECONDS_PER_TRADING_YEAR
        self._sqrt_dtau = math.sqrt(self._dtau)
        self._p_event = min(1.0, event_rate_per_min / 60.0 * update_interval)
        self._mean_reversion = mean_reversion
        self._rng = np.random.default_rng(seed)
        self._state: dict[str, TickerState] = {}
        self._task: asyncio.Task | None = None
        self._running = False
        self.events: deque[tuple[str, float]] = deque(maxlen=100)  # recent (ticker, jump %)
        self.event_count = 0  # total events ever, for consumers tailing ``events``

    # --- MarketDataSource ---

    async def start(self, tickers: Iterable[str]) -> None:
        for t in tickers:
            await self.add_ticker(t)
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._run(), name="simulator-loop")
        logger.info(
            "Simulator started: %d tickers, time_scale=%g", len(self._state), self._time_scale
        )

    async def stop(self) -> None:
        self._running = False
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> bool:
        try:
            t = normalize_ticker(ticker)
        except ValueError:
            return False
        if t not in self._state:
            self._state[t] = self._new_state(t)
            self.cache.update(t, self._state[t].session_open)
            logger.info("Simulator: tracking %s at ₩%s", t, f"{self._state[t].session_open:,}")
        return True

    async def remove_ticker(self, ticker: str) -> None:
        try:
            t = normalize_ticker(ticker)
        except ValueError:
            return
        self._state.pop(t, None)
        self.cache.remove(t)

    @property
    def tickers(self) -> frozenset[str]:
        return frozenset(self._state)

    @property
    def status(self) -> SourceStatus:
        return "ok" if self._running else "stopped"

    # --- Simulation ---

    def state(self, ticker: str) -> TickerState | None:
        return self._state.get(ticker)

    def step(self) -> dict[str, int]:
        """Advance every ticker one step. Publishes changed prices; returns them."""
        if not self._state:
            return {}
        rng = self._rng
        z_m = rng.standard_normal()
        sectors = sorted({st.sector for st in self._state.values()})
        z_s = dict(zip(sectors, rng.standard_normal(len(sectors)), strict=True))
        eps = rng.standard_normal(len(self._state))
        jumps = self._draw_jumps()

        published: dict[str, int] = {}
        for i, (t, st) in enumerate(self._state.items()):
            shock = st.beta_m * z_m + st.beta_s * z_s[st.sector] + st.beta_e * eps[i]
            dx = (st.mu - 0.5 * st.sigma**2) * self._dtau + st.sigma * self._sqrt_dtau * shock
            if self._mean_reversion:
                dx -= st.kappa * (st.x - st.x_bar) * self._dt
            dx += jumps.get(t, 0.0)
            st.x = self._clamp_log(st, st.x + dx)

            price = min(max(snap_to_tick(math.exp(st.x)), st.lower), st.upper)
            if price != self.cache.price(t):
                self.cache.update(t, price)
                published[t] = price
        return published

    def _draw_jumps(self) -> dict[str, float]:
        """Log-jumps for this step, including occasional same-sector contagion."""
        if self._p_event <= 0:
            return {}
        jumps: dict[str, float] = {}
        hits = self._rng.random(len(self._state)) < self._p_event
        for hit, (t, st) in zip(hits, self._state.items(), strict=True):
            if not hit:
                continue
            magnitude = self._rng.uniform(JUMP_MIN, JUMP_MAX)
            sign = 1.0 if self._rng.random() < 0.5 else -1.0
            jumps[t] = jumps.get(t, 0.0) + math.log1p(sign * magnitude)
            self.events.append((t, round(sign * magnitude * 100, 2)))
            self.event_count += 1
            logger.info("Simulator event: %s %+.1f%%", t, sign * magnitude * 100)
            if st.sector != DEFAULT_SECTOR and self._rng.random() < CONTAGION_PROB:
                peer_jump = math.log1p(sign * magnitude * CONTAGION_FRACTION)
                for peer, pst in self._state.items():
                    if peer != t and pst.sector == st.sector:
                        jumps[peer] = jumps.get(peer, 0.0) + peer_jump
        return jumps

    @staticmethod
    def _clamp_log(st: TickerState, x: float) -> float:
        lo = math.log(st.session_open * (1 - PRICE_LIMIT))
        hi = math.log(st.session_open * (1 + PRICE_LIMIT))
        return min(max(x, lo), hi)

    def _new_state(self, ticker: str) -> TickerState:
        params = SEED_PARAMS.get(ticker)
        if params:
            seed, sector, sigma = params.seed_price, params.sector, params.sigma
            beta_m, beta_s, mu = params.beta_m, params.beta_s, params.mu
        else:
            seed, sector, sigma = stable_seed_price(ticker), DEFAULT_SECTOR, DEFAULT_SIGMA
            beta_m, beta_s, mu = DEFAULT_BETA_M, 0.0, 0.05
        beta_e = math.sqrt(max(0.0, 1.0 - beta_m**2 - beta_s**2))
        sigma_real_sq = sigma**2 * self._time_scale / SECONDS_PER_TRADING_YEAR  # per second
        kappa = sigma_real_sq / (2 * STATIONARY_LOG_STD**2)
        lower, upper = limit_band(seed)
        return TickerState(
            ticker=ticker,
            sector=sector,
            mu=mu,
            sigma=sigma,
            beta_m=beta_m,
            beta_s=beta_s,
            beta_e=beta_e,
            kappa=kappa,
            x=math.log(seed),
            x_bar=math.log(seed),
            session_open=seed,
            lower=lower,
            upper=upper,
        )

    async def _run(self) -> None:
        next_t = time.monotonic()
        while True:
            try:
                self.step()
            except Exception:
                logger.exception("Simulator step failed")
            next_t += self._dt
            now = time.monotonic()
            if next_t < now - self._dt:  # fell far behind (e.g. laptop sleep): resync
                next_t = now
            await asyncio.sleep(max(0.0, next_t - now))
