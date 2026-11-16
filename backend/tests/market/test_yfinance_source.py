import asyncio

import pandas as pd
import pytest

from app.market.cache import PriceCache
from app.market.listing import ListingEntry
from app.market.yfinance_source import YFinanceSource, parse_download

LISTING = {
    "005930": ListingEntry("005930", "Samsung Electronics", "KOSPI"),
    "247540": ListingEntry("247540", "Ecopro BM", "KOSDAQ"),
}


class Fake:
    def __init__(self, known=None, batch=None):
        self.known = known or {}  # symbol -> price
        self.batch = batch if batch is not None else dict(self.known)
        self.fail = False
        self.probed = []

    def last_price(self, symbol):
        self.probed.append(symbol)
        return self.known.get(symbol)

    def batch_fn(self, symbols):
        if self.fail:
            raise RuntimeError("boom")
        return {s: self.batch[s] for s in symbols if s in self.batch}


def make(fake, listing=LISTING, interval=0.01):
    cache = PriceCache()
    src = YFinanceSource(cache, poll_interval=interval, listing=listing,
                         last_price_fn=fake.last_price, batch_fn=fake.batch_fn)  # fmt: skip
    return cache, src


def frame(data):
    cols = pd.MultiIndex.from_product([list(data), ["Close"]])
    n = max(len(v) for v in data.values())
    return pd.DataFrame({(s, "Close"): v + [float("nan")] * (n - len(v)) for s, v in data.items()}, columns=cols)


def test_parse_download_multiindex_last_non_nan():
    df = frame({"005930.KS": [75000.0, 75400.0, float("nan")], "000660.KS": [float("nan")]})
    out = parse_download(df, ["005930.KS", "000660.KS", "MISSING.KS"])
    assert out == {"005930.KS": 75400.0}


def test_parse_download_flat_columns_and_empty():
    df = pd.DataFrame({"Close": [1.0, 2.0]})
    assert parse_download(df, ["005930.KS"]) == {"005930.KS": 2.0}
    assert parse_download(pd.DataFrame(), ["x"]) == {}
    assert parse_download(None, ["x"]) == {}


def test_parse_download_rejects_nonpositive():
    assert parse_download(frame({"A.KS": [0.0]}), ["A.KS"]) == {}


async def test_listing_decides_suffix():
    f = Fake({"005930.KS": 75030.0, "247540.KQ": 250000.0})
    cache, src = make(f)
    assert await src.add_ticker("005930")
    assert await src.add_ticker("247540")
    assert src._symbols == {"005930": "005930.KS", "247540": "247540.KQ"}
    assert cache.price("005930") == 75000  # snapped to tick 100
    assert cache.price("247540") == 250000


async def test_unknown_ticker_probes_ks_then_kq():
    f = Fake({"123456.KQ": 8000.0})
    cache, src = make(f, listing={})
    assert await src.add_ticker("123456")
    assert f.probed == ["123456.KS", "123456.KQ"]
    assert src._symbols["123456"] == "123456.KQ"


async def test_unknown_everywhere_returns_false():
    cache, src = make(Fake(), listing={})
    assert await src.add_ticker("999999") is False
    assert src.tickers == frozenset() and cache.get("999999") is None


async def test_invalid_ticker_false_and_idempotent_add():
    f = Fake({"005930.KS": 75000.0})
    cache, src = make(f)
    assert await src.add_ticker("AAPL") is False
    await src.add_ticker("005930")
    n = len(f.probed)
    assert await src.add_ticker("005930") is True
    assert len(f.probed) == n


async def test_poll_updates_only_changes_and_skips_missing():
    f = Fake({"005930.KS": 75000.0})
    cache, src = make(f)
    await src.add_ticker("005930")
    v = cache.version
    assert await src.poll_once()
    assert cache.version == v  # unchanged price not rewritten
    f.batch = {"005930.KS": 75430.0}
    await src.poll_once()
    q = cache.get("005930")
    assert (q.price, q.prev_price, q.session_open) == (75400, 75000, 75000)
    f.batch = {}  # NaN / missing -> keep last
    await src.poll_once()
    assert cache.price("005930") == 75400


async def test_failures_degrade_backoff_and_recover():
    f = Fake({"005930.KS": 75000.0})
    cache, src = make(f, interval=15.0)
    await src.start({"005930"})
    await src.stop()
    src._running = True
    f.fail = True
    for _ in range(3):
        assert await src.poll_once() is False
    assert src.status == "degraded"
    assert src.next_delay() == 15.0 * 2**3
    for _ in range(10):
        await src.poll_once()
    assert src.next_delay() == 300.0
    assert cache.price("005930") == 75000  # last good price retained
    f.fail = False
    assert await src.poll_once()
    assert src.status == "ok" and src.next_delay() == 15.0


async def test_remove_during_flight_not_reinserted():
    f = Fake({"005930.KS": 75000.0})
    cache, src = make(f)
    await src.add_ticker("005930")
    orig = f.batch_fn

    def slow(symbols):
        out = orig(symbols)
        asyncio.run_coroutine_threadsafe(src.remove_ticker("005930"), loop).result()
        return out

    loop = asyncio.get_running_loop()
    src._batch = slow
    f.batch = {"005930.KS": 80000.0}
    task = asyncio.create_task(src.poll_once())
    await task
    assert cache.get("005930") is None and src.tickers == frozenset()


async def test_lifecycle_loop_and_idempotent_stop():
    f = Fake({"005930.KS": 75000.0})
    cache, src = make(f, interval=0.01)
    assert src.status == "stopped"
    await src.start({"005930"})
    assert src.status == "ok"
    f.batch = {"005930.KS": 76000.0}
    await asyncio.sleep(0.15)
    assert cache.price("005930") == 76000
    await src.stop()
    await src.stop()
    assert src.status == "stopped"
    await src.remove_ticker("005930")
    await src.remove_ticker("005930")


@pytest.mark.parametrize("bad", [float("nan"), 0, -1, None])
async def test_bad_probe_prices_not_cached(bad):
    cache, src = make(Fake(), listing=LISTING)
    src._last_price = lambda s: bad if False else None
    assert await src.add_ticker("005930") is True  # listed, but no price yet
    assert cache.get("005930") is None
