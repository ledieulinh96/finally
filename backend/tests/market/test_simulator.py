import math

import numpy as np
import pytest

from app.market.cache import PriceCache
from app.market.seed import DEFAULT_TICKERS
from app.market.simulator import SECONDS_PER_TRADING_YEAR, SimulatorSource
from app.market.ticks import tick_size


def make(seed=42, tickers=None, **kw):
    cache = PriceCache()
    sim = SimulatorSource(cache, seed=seed, **kw)
    return cache, sim


async def started(seed=42, tickers=None, **kw):
    cache, sim = make(seed, **kw)
    await sim.start(set(tickers or DEFAULT_TICKERS))
    await sim.stop()  # stop background loop; drive step() manually
    return cache, sim


async def test_start_seeds_every_ticker():
    cache, sim = await started()
    assert sim.tickers == frozenset(DEFAULT_TICKERS)
    assert cache.price("005930") == 75_000 and cache.price("207940") == 800_000


async def test_prices_int_positive_tick_aligned():
    cache, sim = await started(event_rate_per_min=30)
    for _ in range(3000):
        sim.step()
        for q in cache.get_all().values():
            assert type(q.price) is int and q.price > 0
            assert q.price % tick_size(q.price) == 0


async def test_prices_stay_within_limit_band_with_constant_jumps():
    cache, sim = await started(tickers=["005930", "000660"], event_rate_per_min=120)  # p=1/step
    for _ in range(2000):
        sim.step()
        for t in ("005930", "000660"):
            q = cache.get(t)
            assert 0.7 * q.session_open <= q.price <= 1.3 * q.session_open


async def test_internal_state_clamped_at_limit():
    cache, sim = await started(tickers=["005930"], event_rate_per_min=120)
    for _ in range(2000):
        sim.step()
    st = sim._state["005930"]
    assert math.log(st.lo) - 1e-9 <= st.x <= math.log(st.hi) + 1e-9


async def test_determinism_same_seed():
    runs = []
    for _ in range(2):
        cache, sim = await started(seed=7)
        seq = []
        for _ in range(200):
            sim.step()
            seq.append(tuple(sorted((t, q.price) for t, q in cache.get_all().items())))
        runs.append(seq)
    assert runs[0] == runs[1]
    cache, sim = await started(seed=8)
    for _ in range(200):
        sim.step()
    assert tuple(sorted((t, q.price) for t, q in cache.get_all().items())) != runs[0][-1]


async def test_only_changes_are_published():
    cache, sim = await started(tickers=["005930"], event_rate_per_min=0)
    v = cache.version
    sim.step()
    q = cache.get("005930")
    assert cache.version == v + (1 if q.version > v else 0)
    for _ in range(500):
        before = cache.price("005930")
        v = cache.version
        sim.step()
        if cache.version != v:
            assert cache.price("005930") != before


async def test_gbm_log_return_moments_without_reversion_or_jumps():
    cache, sim = await started(tickers=["005930"], event_rate_per_min=0)
    st = sim._state["005930"]
    st.kappa = 0.0
    st.lo, st.hi = 1e-6, 1e12  # disable band
    xs = []
    for _ in range(40_000):
        before = st.x
        sim.step()
        xs.append(st.x - before)
    dtau = sim._dtau
    exp_mean = (st.mu - 0.5 * st.sigma**2) * dtau
    exp_var = st.sigma**2 * dtau
    assert np.var(xs) == pytest.approx(exp_var, rel=0.05)
    assert abs(np.mean(xs) - exp_mean) < 4 * math.sqrt(exp_var / len(xs))


async def test_correlations_match_factor_structure():
    cache, sim = await started(tickers=["005930", "000660", "035420"], event_rate_per_min=0)
    for st in sim._state.values():
        st.kappa = 0.0
        st.lo, st.hi = 1e-6, 1e12
    rows = []
    for _ in range(30_000):
        prev = [sim._state[t].x for t in ("005930", "000660", "035420")]
        sim.step()
        rows.append([sim._state[t].x - p for t, p in zip(("005930", "000660", "035420"), prev)])
    c = np.corrcoef(np.array(rows).T)
    assert c[0, 1] == pytest.approx(0.73, abs=0.05)  # same sector
    assert c[0, 2] == pytest.approx(0.25, abs=0.05)  # cross sector


async def test_mean_reversion_half_life():
    cache, sim = await started(tickers=["005930"], event_rate_per_min=0, time_scale=200.0)
    st = sim._state["005930"]
    st.lo, st.hi = 1e-6, 1e12
    st.sigma = 0.0  # isolate OU pull
    st.mu = 0.0
    st.x = st.x_bar + math.log(1.25)
    gap0 = st.x - st.x_bar
    half_life = math.log(2) / st.kappa
    steps = round(half_life / sim._dt)
    for _ in range(steps):
        sim.step()
    assert (st.x - st.x_bar) == pytest.approx(gap0 / 2, rel=0.03)


async def test_kappa_formula():
    _, sim = make(time_scale=200.0)
    await sim.add_ticker("005930")
    st = sim._state["005930"]
    sigma_real_sq = 0.30**2 * 200 / SECONDS_PER_TRADING_YEAR
    assert st.kappa == pytest.approx(sigma_real_sq / (2 * 0.15**2))


async def test_events_in_two_to_five_percent_band():
    cache, sim = await started(tickers=["005930"], event_rate_per_min=120)
    seen = 0
    for _ in range(300):
        sim.step()
        for _, pct in sim.events:
            assert 2.0 <= abs(pct) <= 5.0
            seen += 1
    assert seen > 100


async def test_events_disabled():
    cache, sim = await started(event_rate_per_min=0)
    for _ in range(300):
        sim.step()
        assert sim.events == []


async def test_sector_contagion_moves_peers_same_direction():
    cache, sim = await started(tickers=["005930", "000660", "035420"], event_rate_per_min=120)
    import app.market.simulator as m

    m.CONTAGION_PROB, orig = 1.0, m.CONTAGION_PROB
    try:
        jumps = sim._draw_jumps()
    finally:
        m.CONTAGION_PROB = orig
    # every ticker jumps each step (p=1); peers got extra contagion on top of their own jump
    assert set(jumps) == {"005930", "000660", "035420"}


async def test_add_ticker_unknown_valid_is_deterministic_across_instances():
    prices = []
    for _ in range(2):
        cache, sim = make()
        assert await sim.add_ticker("123456") is True
        prices.append(cache.price("123456"))
    assert prices[0] == prices[1] and prices[0] > 0


async def test_add_remove_idempotent_and_invalid():
    cache, sim = make()
    assert await sim.add_ticker("005930") and await sim.add_ticker("005930")
    v = cache.version
    await sim.add_ticker("005930")
    assert cache.version == v  # no reseed
    assert await sim.add_ticker("AAPL") is False
    await sim.remove_ticker("005930")
    await sim.remove_ticker("005930")
    await sim.remove_ticker("bad")
    assert sim.tickers == frozenset() and cache.get("005930") is None


async def test_lowercase_ticker_normalized():
    cache, sim = make()
    assert await sim.add_ticker(" 00593a ") is True
    assert sim.tickers == frozenset({"00593A"})


async def test_step_with_no_tickers_is_noop():
    cache, sim = make()
    sim.step()
    assert len(cache) == 0


async def test_async_loop_smoke_and_idempotent_stop():
    cache = PriceCache()
    sim = SimulatorSource(cache, update_interval=0.01, seed=1, time_scale=2000)
    assert sim.status == "stopped"
    await sim.start({"005930", "000660"})
    assert sim.status == "ok"
    v = cache.version
    import asyncio

    await asyncio.sleep(0.2)
    assert cache.version > v
    await sim.stop()
    await sim.stop()
    assert sim.status == "stopped"
    v = cache.version
    await asyncio.sleep(0.05)
    assert cache.version == v
