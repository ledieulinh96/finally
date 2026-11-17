"""GBM market simulator: correlated sector moves, mean reversion, jumps, KRX ticks."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from dataclasses import dataclass

import numpy as np

from .base import MarketDataSource
from .cache import PriceCache
from .seed import SeedParams, normalize_ticker, params_for
from .ticks import snap_down, snap_to_tick, snap_up

logger = logging.getLogger(__name__)

SECONDS_PER_TRADING_YEAR = 252 * 6.5 * 3600  # 5,896,800
LIMIT_PCT = 0.30
STATIONARY_STD = 0.15
CONTAGION_PROB = 0.3
CONTAGION_SHARE = 0.4


@dataclass
class TickerState:
    ticker: str
    sector: str
    mu: float
    sigma: float
    bm: float
    bs: float
    be: float
    kappa: float
    x: float  # log of internal float price
    x_bar: float  # log of seed price
    open_price: float  # seed price (session open)
    lo: float  # price band in KRW (internal)
    hi: float
    pub_lo: int  # tick-aligned published band
    pub_hi: int


class SimulatorSource(MarketDataSource):
    def __init__(
        self,
        cache: PriceCache,
        update_interval: float = 0.5,
        time_scale: float = 200.0,
        seed: int | None = None,
        event_rate_per_min: float = 0.1,
    ) -> None:
        super().__init__(cache)
        self._rng = np.random.default_rng(seed)
        self._dt = update_interval
        self._scale = time_scale
        self._dtau = update_interval * time_scale / SECONDS_PER_TRADING_YEAR
        self._p_event = min(1.0, max(0.0, event_rate_per_min / 60.0 * update_interval))
        self._state: dict[str, TickerState] = {}
        self._task: asyncio.Task | None = None
        self.events: list[tuple[str, float]] = []  # (ticker, jump pct) of the last step

    # ---- lifecycle -------------------------------------------------------------

    async def start(self, tickers: set[str]) -> None:
        for t in sorted(tickers):
            await self.add_ticker(t)
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="simulator-loop")

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def add_ticker(self, ticker: str) -> bool:
        try:
            ticker = normalize_ticker(ticker)
        except ValueError:
            return False
        if ticker in self._state:
            return True
        st = self._make_state(ticker, params_for(ticker))
        self._state[ticker] = st
        self.cache.update(ticker, snap_to_tick(st.open_price))
        return True

    async def remove_ticker(self, ticker: str) -> None:
        try:
            ticker = normalize_ticker(ticker)
        except ValueError:
            return
        self._state.pop(ticker, None)
        self.cache.remove(ticker)

    @property
    def tickers(self) -> frozenset[str]:
        return frozenset(self._state)

    @property
    def status(self) -> str:
        return "ok" if self._task and not self._task.done() else "stopped"

    # ---- model -----------------------------------------------------------------

    def _make_state(self, ticker: str, p: SeedParams) -> TickerState:
        seed = float(p.seed_price)
        sigma_real_sq = p.sigma**2 * self._scale / SECONDS_PER_TRADING_YEAR
        kappa = sigma_real_sq / (2 * STATIONARY_STD**2)
        lo, hi = seed * (1 - LIMIT_PCT), seed * (1 + LIMIT_PCT)
        x0 = math.log(seed)
        return TickerState(
            ticker, p.sector, p.mu, p.sigma, p.beta_m, p.beta_s, p.beta_e, kappa,
            x0, x0, seed, lo, hi, snap_up(lo), snap_down(hi),
        )  # fmt: skip

    def _draw_jumps(self) -> dict[str, float]:
        """Per-ticker log jump for this step (with sector contagion)."""
        jumps: dict[str, float] = {}
        self.events = []
        if self._p_event <= 0:
            return jumps
        for t, st in self._state.items():
            if self._rng.random() < self._p_event:
                mag = self._rng.uniform(0.02, 0.05)
                sign = 1.0 if self._rng.random() < 0.5 else -1.0
                j = math.log(1 + sign * mag)
                jumps[t] = jumps.get(t, 0.0) + j
                self.events.append((t, round(sign * mag * 100, 2)))
                logger.info("Simulator event: %s %+.2f%%", t, sign * mag * 100)
                if st.sector != "other" and self._rng.random() < CONTAGION_PROB:
                    for u, ost in self._state.items():
                        if u != t and ost.sector == st.sector:
                            jumps[u] = jumps.get(u, 0.0) + j * CONTAGION_SHARE
        return jumps

    def step(self) -> None:
        """One simulation step. Public so tests can drive it without asyncio."""
        if not self._state:
            return
        z_m = self._rng.standard_normal()
        z_s = {s: self._rng.standard_normal() for s in sorted({st.sector for st in self._state.values()})}
        jumps = self._draw_jumps()
        sqrt_dtau = math.sqrt(self._dtau)
        for t, st in self._state.items():
            shock = st.bm * z_m + st.bs * z_s[st.sector] + st.be * self._rng.standard_normal()
            dx = (st.mu - 0.5 * st.sigma**2) * self._dtau + st.sigma * sqrt_dtau * shock
            dx -= st.kappa * (st.x - st.x_bar) * self._dt
            dx += jumps.get(t, 0.0)
            st.x = min(max(st.x + dx, math.log(st.lo)), math.log(st.hi))
            price = min(max(snap_to_tick(math.exp(st.x)), st.pub_lo), st.pub_hi)
            if price != self.cache.price(t):
                self.cache.update(t, price)

    async def _run(self) -> None:
        next_t = time.monotonic()
        while True:
            try:
                self.step()
            except Exception:  # never let the loop die
                logger.exception("Simulator step failed")
            next_t += self._dt
            await asyncio.sleep(max(0.0, next_t - time.monotonic()))
