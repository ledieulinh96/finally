import threading
from datetime import UTC, datetime

import pytest

from app.market.cache import PriceCache


def test_first_update_sets_prev_and_open_to_price():
    c = PriceCache()
    q = c.update("005930", 75000)
    assert (q.prev_price, q.session_open, q.direction) == (75000, 75000, "flat")
    assert q.timestamp.tzinfo is not None


def test_update_tracks_prev_and_keeps_open():
    c = PriceCache()
    c.update("005930", 75000)
    c.update("005930", 75100)
    q = c.update("005930", 75300)
    assert (q.prev_price, q.session_open, q.price) == (75100, 75000, 75300)


def test_explicit_timestamp_used():
    ts = datetime(2026, 1, 1, tzinfo=UTC)
    assert PriceCache().update("005930", 1000, ts).timestamp == ts


@pytest.mark.parametrize("bad", [0, -5, 75000.5, True, None])
def test_rejects_non_positive_or_non_int(bad):
    with pytest.raises(ValueError):
        PriceCache().update("005930", bad)


def test_get_price_all_len_contains():
    c = PriceCache()
    assert c.get("x") is None and c.price("x") is None and len(c) == 0
    c.update("005930", 75000)
    assert c.price("005930") == 75000 and "005930" in c and len(c) == 1
    snap = c.get_all()
    snap.clear()
    assert len(c) == 1  # copy


def test_changed_since_and_version():
    c = PriceCache()
    c.update("A", 1000)
    v = c.version
    c.update("B", 2000)
    c.update("A", 1005)
    got = c.changed_since(v)
    assert [q.ticker for q in got] == ["B", "A"]
    assert c.changed_since(c.version) == []
    assert len(c.changed_since(0)) == 2


def test_remove_idempotent():
    c = PriceCache()
    c.update("A", 1000)
    c.remove("A")
    c.remove("A")
    assert c.get("A") is None
    c.update("A", 1200)
    assert c.get("A").session_open == 1200  # fresh session baseline


def test_concurrent_writes_lose_nothing():
    c = PriceCache()

    def work(n):
        for i in range(500):
            c.update(f"T{n}", 1000 + i)

    ts = [threading.Thread(target=work, args=(n,)) for n in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert c.version == 4000
