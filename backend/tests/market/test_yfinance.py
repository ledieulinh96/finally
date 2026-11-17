"""YFinanceSource with a fake fetcher — no network."""

import asyncio
import math

import pandas as pd
import pytest

from app.market.cache import PriceCache
from app.market.names import NameRegistry
from app.market.yfinance_source import MAX_BACKOFF, YahooFetcher, YFinanceSource

from .fakes import FakeFetcher


def make(prices=None, **kw):
    fetcher = FakeFetcher(prices, kw.pop("short_names", None))
    names = kw.pop("names", None)
    src = YFinanceSource(
        PriceCache(), poll_interval=kw.pop("poll_interval", 15.0), fetcher=fetcher, names=names
    )
    return src, fetcher


async def test_listing_maps_kospi_and_kosdaq_suffixes_without_probing():
    src, f = make({"005930.KS": 75_430.0, "247540.KQ": 151_234.0})
    assert await src.add_ticker("005930")
    assert await src.add_ticker("247540")
    assert src.symbol_for("005930") == "005930.KS"
    assert src.symbol_for("247540") == "247540.KQ"
    assert f.probe_calls == []
    assert src.cache.price("005930") == 75_400  # snapped to ₩100 tick
    assert src.cache.price("247540") == 151_200


async def test_unlisted_ticker_probes_ks_then_kq_and_learns_name():
    names = NameRegistry()
    src, f = make({"900111.KQ": 3_333.0}, short_names={"900111.KQ": "Some Co"}, names=names)
    assert await src.add_ticker("900111")
    assert f.probe_calls == ["900111.KS", "900111.KQ"]
    assert src.symbol_for("900111") == "900111.KQ"
    assert src.cache.price("900111") == 3_335
    assert names.get("900111") == "Some Co"


async def test_unknown_ticker_returns_false_and_is_not_tracked():
    src, _ = make({})
    assert not await src.add_ticker("999999")
    assert "999999" not in src.tickers and "999999" not in src.cache


async def test_failed_probe_is_not_memoized():
    src, f = make({})
    f.fail = True
    assert not await src.add_ticker("900222")
    f.fail = False
    f.prices["900222.KS"] = 10_000.0
    assert await src.add_ticker("900222")


async def test_invalid_ticker_rejected():
    src, _ = make({})
    assert not await src.add_ticker("AAPL")


async def test_start_does_one_batched_poll_and_prices_everything():
    src, f = make({"005930.KS": 75_000.0, "000660.KS": 180_000.0})
    await src.start(["005930", "000660", "nope!"])
    try:
        assert src.tickers == frozenset({"005930", "000660"})
        assert sorted(f.batch_calls[-1]) == ["000660.KS", "005930.KS"]
        assert src.cache.price("000660") == 180_000
        assert src.status == "ok"
    finally:
        await src.stop()
    assert src.status == "stopped"


async def test_poll_only_writes_changed_prices_and_keeps_missing():
    src, f = make({"005930.KS": 75_000.0, "000660.KS": 180_000.0})
    await src.add_ticker("005930")
    await src.add_ticker("000660")
    v = src.cache.version
    assert await src.poll_once()
    assert src.cache.version == v  # nothing changed → no flat spam
    f.prices["005930.KS"] = 75_100.0
    f.prices["000660.KS"] = math.nan  # NaN row: keep last price
    assert await src.poll_once()
    assert src.cache.version == v + 1
    assert src.cache.get("005930").direction == "up"
    assert src.cache.price("000660") == 180_000
    del f.prices["000660.KS"]  # delisted / missing
    assert await src.poll_once()
    assert src.cache.price("000660") == 180_000


async def test_session_open_is_first_price_seen():
    src, f = make({"005930.KS": 75_000.0})
    await src.add_ticker("005930")
    f.prices["005930.KS"] = 76_500.0
    await src.poll_once()
    q = src.cache.get("005930")
    assert q.session_open == 75_000 and q.session_change_pct == 2.0


async def test_backoff_and_degraded_status():
    src, f = make({"005930.KS": 75_000.0}, poll_interval=15.0)
    await src.add_ticker("005930")
    src._running = True
    f.fail = True
    delays = []
    for _ in range(6):
        assert not await src.poll_once()
        delays.append(src.next_delay())
    assert delays[:3] == [30.0, 60.0, 120.0]
    assert delays[-1] == MAX_BACKOFF
    assert src.status == "degraded"
    assert src.cache.price("005930") == 75_000  # last price kept
    f.fail = False
    assert await src.poll_once()
    assert src.status == "ok" and src.next_delay() == 15.0


async def test_add_ticker_survives_first_fetch_failure():
    src, f = make({"005930.KS": 75_000.0})
    f.fail = True
    assert await src.add_ticker("005930")  # listed → tracked; priced on next poll
    assert src.cache.price("005930") is None
    f.fail = False
    await src.poll_once()
    assert src.cache.price("005930") == 75_000


async def test_remove_is_idempotent_and_clears_cache():
    src, _ = make({"005930.KS": 75_000.0})
    await src.add_ticker("005930")
    await src.remove_ticker("005930")
    await src.remove_ticker("005930")
    await src.remove_ticker("??")
    assert src.tickers == frozenset() and "005930" not in src.cache


async def test_background_loop_polls():
    src, f = make({"005930.KS": 75_000.0}, poll_interval=0.01)
    await src.start(["005930"])
    f.prices["005930.KS"] = 75_500.0
    await asyncio.sleep(0.1)
    await src.stop()
    assert src.cache.price("005930") == 75_500
    assert len(f.batch_calls) >= 3


def test_yahoo_fetcher_parses_multiindex_frame(monkeypatch):
    import yfinance as yf

    idx = pd.date_range("2026-11-13 09:00", periods=3, freq="min", tz="Asia/Seoul")
    cols = pd.MultiIndex.from_product([["005930.KS", "000660.KS"], ["Open", "Close"]])
    df = pd.DataFrame(
        [
            [75_000, 75_000, 180_000, 180_000],
            [75_000, 75_100, 180_000, float("nan")],
            [75_100, float("nan"), 180_000, float("nan")],
        ],
        index=idx,
        columns=cols,
    )
    monkeypatch.setattr(yf, "download", lambda **kw: df)
    out = YahooFetcher().fetch_batch(["005930.KS", "000660.KS", "123456.KS"])
    assert out == {"005930.KS": 75_100.0, "000660.KS": 180_000.0}


def test_yahoo_fetcher_handles_empty_and_flat_frames(monkeypatch):
    import yfinance as yf

    monkeypatch.setattr(yf, "download", lambda **kw: pd.DataFrame())
    assert YahooFetcher().fetch_batch(["005930.KS"]) == {}
    assert YahooFetcher().fetch_batch([]) == {}
    flat = pd.DataFrame({"Close": [75_000.0, 75_200.0]})
    monkeypatch.setattr(yf, "download", lambda **kw: flat)
    assert YahooFetcher().fetch_batch(["005930.KS"]) == {"005930.KS": 75_200.0}


def test_yahoo_fetcher_probe_and_short_name(monkeypatch):
    import yfinance as yf

    class FakeTicker:
        def __init__(self, symbol):
            self.symbol = symbol

        @property
        def fast_info(self):
            if self.symbol.startswith("005930"):
                return {"last_price": 75_000.0}
            raise KeyError("unknown")

        @property
        def info(self):
            return {"shortName": " SamsungElec "} if self.symbol.startswith("005930") else {}

    monkeypatch.setattr(yf, "Ticker", FakeTicker)
    fetcher = YahooFetcher()
    assert fetcher.probe("005930.KS") == 75_000.0
    assert fetcher.probe("999999.KS") is None
    assert fetcher.short_name("005930.KS") == "SamsungElec"
    assert fetcher.short_name("999999.KS") is None


@pytest.mark.parametrize("bad", [None, "x", math.inf, -1.0, 0])
def test_invalid_prices_ignored(bad):
    from app.market.yfinance_source import _valid_price

    assert _valid_price(bad) is None
