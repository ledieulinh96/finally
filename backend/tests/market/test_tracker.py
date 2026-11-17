import pytest

from app.market.cache import PriceCache
from app.market.simulator import SimulatorSource
from app.market.tracker import PriceUnavailableError, TickerTracker


def setup(watch, pos):
    cache = PriceCache()
    src = SimulatorSource(cache, seed=1)
    state = {"w": set(watch), "p": set(pos)}
    return cache, src, state, TickerTracker(src, lambda: state["w"], lambda: state["p"])


async def test_sync_tracks_union():
    _, src, st, tr = setup({"005930"}, {"000660"})
    assert await tr.sync() == set()
    assert src.tickers == {"005930", "000660"}


async def test_held_ticker_stays_after_watchlist_removal_then_untracked_after_sell():
    cache, src, st, tr = setup({"005930", "000660"}, {"000660"})
    await tr.sync()
    st["w"].discard("000660")
    await tr.sync()
    assert "000660" in src.tickers and cache.price("000660")
    st["p"].discard("000660")
    await tr.sync()
    assert "000660" not in src.tickers and cache.get("000660") is None


async def test_sync_reports_unpriceable():
    _, src, st, tr = setup({"005930", "BAD"}, set())
    assert await tr.sync() == {"BAD"}


async def test_price_for_trade_adds_untracked():
    cache, src, st, tr = setup(set(), set())
    assert await tr.price_for_trade("005930") == 75_000
    assert "005930" in src.tickers


async def test_price_for_trade_rejects_unpriceable():
    _, _, _, tr = setup(set(), set())
    with pytest.raises(PriceUnavailableError, match="No price available"):
        await tr.price_for_trade("NOPE")
