"""SimulatorSource: KRX realism, GBM math, correlation, mean reversion, determinism."""

import asyncio
import math

import numpy as np
import pytest

from app.market.cache import PriceCache
from app.market.seed_data import DEFAULT_TICKERS, SEED_PARAMS
from app.market.simulator import SECONDS_PER_TRADING_YEAR, SimulatorSource, stable_seed_price
from app.market.ticks import tick_size


async def make_sim(tickers=DEFAULT_TICKERS, **kw) -> SimulatorSource:
    sim = SimulatorSource(PriceCache(), **kw)
    for t in tickers:
        assert await sim.add_ticker(t)
    return sim


def internal_log_returns(sim, tickers, steps):
    out = np.empty((steps, len(tickers)))
    prev = np.array([sim.state(t).x for t in tickers])
    for k in range(steps):
        sim.step()
        cur = np.array([sim.state(t).x for t in tickers])
        out[k] = cur - prev
        prev = cur
    return out


async def test_add_ticker_writes_seed_price_immediately():
    sim = await make_sim()
    for t in DEFAULT_TICKERS:
        q = sim.cache.get(t)
        assert q is not None and q.price == SEED_PARAMS[t].seed_price
        assert q.session_open == q.price


async def test_prices_are_int_positive_tick_aligned_and_in_band():
    sim = await make_sim(seed=1)
    for _ in range(5_000):
        sim.step()
        for t in DEFAULT_TICKERS:
            q = sim.cache.get(t)
            assert isinstance(q.price, int) and q.price > 0
            assert q.price % tick_size(q.price) == 0
            assert 0.7 * q.session_open <= q.price <= 1.3 * q.session_open


async def test_band_holds_under_constant_jumps():
    sim = await make_sim(seed=3, event_rate_per_min=10_000, time_scale=5_000)
    for _ in range(2_000):
        sim.step()
    for t in DEFAULT_TICKERS:
        q = sim.cache.get(t)
        assert 0.7 * q.session_open <= q.price <= 1.3 * q.session_open
        st = sim.state(t)
        assert (
            math.log(0.7 * st.session_open) - 1e-9 <= st.x <= math.log(1.3 * st.session_open) + 1e-9
        )


async def test_only_changed_prices_are_published():
    sim = await make_sim(seed=5)
    start_version = sim.cache.version
    published = 0
    for _ in range(500):
        changed = sim.step()
        published += len(changed)
        for t, p in changed.items():
            assert sim.cache.get(t).prev_price != p
    assert sim.cache.version - start_version == published
    assert 0 < published < 500 * len(DEFAULT_TICKERS)  # some steps stay on the same tick


async def test_default_time_scale_makes_the_tape_lively():
    sim = await make_sim(seed=11)
    moves = sum(len(sim.step()) for _ in range(200))
    # ~1 tick per step per ticker at TIME_SCALE=200: well over a third of ticks move.
    assert moves > 0.35 * 200 * len(DEFAULT_TICKERS)


async def test_gbm_log_return_moments():
    ts = 50.0
    sim = await make_sim(
        ["005930"], seed=7, time_scale=ts, event_rate_per_min=0, mean_reversion=False
    )
    r = internal_log_returns(sim, ["005930"], 40_000)[:, 0]
    sigma, mu = 0.30, 0.05
    dtau = 0.5 * ts / SECONDS_PER_TRADING_YEAR
    exp_mean, exp_var = (mu - 0.5 * sigma**2) * dtau, sigma**2 * dtau
    se_mean = math.sqrt(exp_var / len(r))
    assert abs(r.mean() - exp_mean) < 4 * se_mean
    assert r.var() == pytest.approx(exp_var, rel=0.03)


async def test_factor_model_correlations():
    tickers = ["005930", "000660", "035420"]
    sim = await make_sim(tickers, seed=9, time_scale=20, event_rate_per_min=0, mean_reversion=False)
    r = internal_log_returns(sim, tickers, 30_000)
    corr = np.corrcoef(r.T)
    assert corr[0, 1] == pytest.approx(0.55 * 0.50 + 0.65 * 0.70, abs=0.03)  # same sector ≈ 0.73
    assert corr[0, 2] == pytest.approx(0.55 * 0.45, abs=0.03)  # cross sector ≈ 0.25


class _ZeroRng:
    """Deterministic stand-in: no noise, no jumps."""

    def standard_normal(self, size=None):
        return 0.0 if size is None else np.zeros(size)

    def random(self, size=None):
        return 1.0 if size is None else np.ones(size)

    def uniform(self, a, b):
        return a


async def test_mean_reversion_half_life():
    sim = await make_sim(["005930"], event_rate_per_min=0)
    sim._rng = _ZeroRng()
    st = sim.state("005930")
    st.x = st.x_bar + math.log(1.25)
    gap0 = st.x - st.x_bar
    half_life_steps = int(math.log(2) / st.kappa / 0.5)
    for _ in range(half_life_steps):
        sim.step()
    assert (st.x - st.x_bar) / gap0 == pytest.approx(0.5, abs=0.03)
    # κ derived from σ and TIME_SCALE so the stationary band is ~±15%:
    sigma_real_sq = 0.30**2 * 200 / SECONDS_PER_TRADING_YEAR
    assert math.sqrt(sigma_real_sq / (2 * st.kappa)) == pytest.approx(0.15)


async def test_determinism_with_seed():
    a = await make_sim(seed=42)
    b = await make_sim(seed=42)
    for _ in range(300):
        assert a.step() == b.step()
    c = await make_sim(seed=43)
    assert any(a.step() != c.step() for _ in range(50))


async def test_jump_events_are_2_to_5_percent():
    sim = await make_sim(seed=2, event_rate_per_min=600)
    for _ in range(200):
        sim.step()
    assert len(sim.events) > 0
    for _, pct in sim.events:
        assert 2.0 <= abs(pct) <= 5.0


async def test_events_disabled_with_zero_rate():
    sim = await make_sim(seed=2, event_rate_per_min=0)
    for _ in range(2_000):
        sim.step()
    assert len(sim.events) == 0


async def test_unknown_ticker_gets_stable_seed_and_other_sector():
    a = await make_sim(["123456"])
    b = await make_sim(["123456"])
    p = a.cache.price("123456")
    assert p == b.cache.price("123456") == stable_seed_price("123456")
    assert 5_000 * 0.99 <= p <= 500_000 * 1.01 and p % tick_size(p) == 0
    st = a.state("123456")
    assert st.sector == "other" and st.beta_s == 0.0
    assert st.beta_m**2 + st.beta_e**2 == pytest.approx(1.0)


async def test_add_remove_idempotent_and_invalid_rejected():
    sim = await make_sim([])
    assert await sim.add_ticker("005930")
    assert await sim.add_ticker("005930")
    assert await sim.add_ticker("005930.KS")
    assert sim.tickers == frozenset({"005930"})
    assert not await sim.add_ticker("AAPL")
    await sim.remove_ticker("005930")
    await sim.remove_ticker("005930")
    await sim.remove_ticker("bogus")
    assert sim.tickers == frozenset() and "005930" not in sim.cache
    assert sim.step() == {}


@pytest.mark.parametrize(
    "kw", [{"update_interval": 0}, {"time_scale": -1}, {"event_rate_per_min": -1}]
)
def test_invalid_config_rejected(kw):
    with pytest.raises(ValueError):
        SimulatorSource(PriceCache(), **kw)


async def test_background_loop_smoke():
    sim = SimulatorSource(PriceCache(), update_interval=0.01, seed=1)
    assert sim.status == "stopped"
    await sim.start(DEFAULT_TICKERS)
    assert sim.status == "ok"
    v = sim.cache.version
    await asyncio.sleep(0.15)
    assert sim.cache.version > v
    await sim.stop()
    await sim.stop()  # idempotent
    assert sim.status == "stopped"
    v = sim.cache.version
    await asyncio.sleep(0.05)
    assert sim.cache.version == v


async def test_loop_survives_step_exceptions(monkeypatch):
    sim = SimulatorSource(PriceCache(), update_interval=0.01)
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("boom")

    monkeypatch.setattr(sim, "step", boom)
    await sim.start(["005930"])
    await asyncio.sleep(0.08)
    await sim.stop()
    assert calls["n"] >= 3
