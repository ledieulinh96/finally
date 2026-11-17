"""Shared interface suite run against both sources."""

import pytest

from app.market.cache import PriceCache
from app.market.simulator import SimulatorSource
from app.market.ticks import tick_size
from app.market.yfinance_source import YFinanceSource

PRICES = {"005930.KS": 75000.0, "000660.KS": 180000.0, "035420.KS": 200000.0}


def sim(cache):
    return SimulatorSource(cache, seed=1)


def yf(cache):
    return YFinanceSource(cache, last_price_fn=PRICES.get, batch_fn=lambda s: {k: PRICES[k] for k in s if k in PRICES})


@pytest.fixture(params=[sim, yf], ids=["simulator", "yfinance"])
def pair(request):
    cache = PriceCache()
    return cache, request.param(cache)


async def test_start_prices_every_ticker(pair):
    cache, src = pair
    await src.start({"005930", "000660"})
    try:
        assert src.tickers == frozenset({"005930", "000660"})
        for t in src.tickers:
            p = cache.price(t)
            assert type(p) is int and p > 0 and p % tick_size(p) == 0
    finally:
        await src.stop()


async def test_add_remove_idempotent(pair):
    cache, src = pair
    assert await src.add_ticker("035420") and await src.add_ticker("035420")
    assert cache.price("035420")
    await src.remove_ticker("035420")
    await src.remove_ticker("035420")
    assert "035420" not in src.tickers and cache.get("035420") is None


async def test_stop_idempotent_and_status(pair):
    _, src = pair
    await src.stop()
    await src.start({"005930"})
    await src.stop()
    await src.stop()
    assert src.status == "stopped"
