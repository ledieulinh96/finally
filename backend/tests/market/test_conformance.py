"""Every MarketDataSource implementation honours the same contract."""

import pytest

from app.market.base import MarketDataSource
from app.market.cache import PriceCache
from app.market.seed_data import DEFAULT_TICKERS, SEED_PARAMS
from app.market.simulator import SimulatorSource
from app.market.ticks import tick_size
from app.market.yfinance_source import YFinanceSource

from .fakes import FakeFetcher


def simulator():
    return SimulatorSource(PriceCache(), update_interval=0.05, seed=1)


def yfinance():
    prices = {f"{t}.KS": float(p.seed_price) + 37.0 for t, p in SEED_PARAMS.items()}
    return YFinanceSource(PriceCache(), poll_interval=0.05, fetcher=FakeFetcher(prices))


@pytest.fixture(params=[simulator, yfinance], ids=["simulator", "yfinance"])
async def source(request):
    src = request.param()
    yield src
    await src.stop()


async def test_is_a_market_data_source(source):
    assert isinstance(source, MarketDataSource)
    assert source.status == "stopped"


async def test_start_prices_every_ticker(source):
    await source.start(DEFAULT_TICKERS)
    assert source.tickers == frozenset(DEFAULT_TICKERS)
    assert source.status == "ok"
    for t in DEFAULT_TICKERS:
        p = source.cache.price(t)
        assert isinstance(p, int) and p > 0 and p % tick_size(p) == 0


async def test_add_remove_idempotent(source):
    await source.start(["005930"])
    assert await source.add_ticker("000660")
    assert await source.add_ticker("000660")
    assert source.cache.price("000660") is not None
    await source.remove_ticker("000660")
    await source.remove_ticker("000660")
    assert "000660" not in source.tickers and "000660" not in source.cache


async def test_stop_idempotent(source):
    await source.start(["005930"])
    await source.stop()
    await source.stop()
    assert source.status == "stopped"
