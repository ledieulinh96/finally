"""TickerTracker keeps tracked set == watchlist ∪ positions."""

from app.market.cache import PriceCache
from app.market.simulator import SimulatorSource
from app.market.tracker import TickerTracker
from app.market.yfinance_source import YFinanceSource

from .fakes import FakeFetcher


async def test_sync_adds_and_removes():
    src = SimulatorSource(PriceCache(), seed=1)
    tracker = TickerTracker(src)
    assert await tracker.sync(["005930", "000660"]) == set()
    assert src.tickers == {"005930", "000660"}
    await tracker.sync(["005930"])
    assert src.tickers == {"005930"} and "000660" not in src.cache


async def test_held_ticker_stays_tracked_after_watchlist_removal():
    src = SimulatorSource(PriceCache(), seed=1)
    tracker = TickerTracker(src)
    await tracker.sync(["005930", "000660"], positions=["000660"])
    await tracker.sync(["005930"], positions=["000660"])  # removed from watchlist, still held
    assert "000660" in src.tickers and src.cache.price("000660") is not None
    await tracker.sync(["005930"], positions=[])  # sold to zero
    assert "000660" not in src.tickers


async def test_sync_reports_unpriceable_tickers():
    src = YFinanceSource(PriceCache(), fetcher=FakeFetcher({"005930.KS": 75_000.0}))
    tracker = TickerTracker(src)
    assert await tracker.sync(["005930", "999999"]) == {"999999"}
    assert src.tickers == {"005930"}


async def test_ensure_tracks_single_ticker():
    src = SimulatorSource(PriceCache(), seed=1)
    tracker = TickerTracker(src)
    assert await tracker.ensure("035420")
    assert src.cache.price("035420") == 200_000
