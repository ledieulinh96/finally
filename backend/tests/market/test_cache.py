"""PriceCache: versioning, session_open, thread safety, int-only prices."""

import threading

import pytest

from app.market.cache import PriceCache


def test_first_update_is_flat_and_sets_session_open():
    c = PriceCache()
    q = c.update("005930", 75_000)
    assert (q.price, q.prev_price, q.session_open, q.direction) == (75_000, 75_000, 75_000, "flat")
    assert q.version == 1 and c.version == 1


def test_subsequent_update_keeps_session_open():
    c = PriceCache()
    c.update("005930", 75_000)
    c.update("005930", 75_100)
    q = c.update("005930", 74_900)
    assert (q.prev_price, q.session_open, q.direction) == (75_100, 75_000, "down")
    assert c.price("005930") == 74_900


def test_changed_since_returns_only_newer_in_version_order():
    c = PriceCache()
    c.update("A00001", 1_000)
    c.update("B00002", 2_000)
    v = c.version
    c.update("B00002", 2_005)
    c.update("A00001", 1_001)
    changed = c.changed_since(v)
    assert [q.ticker for q in changed] == ["B00002", "A00001"]
    assert c.changed_since(c.version) == []
    assert len(c.changed_since(0)) == 2


def test_remove_get_all_len_contains():
    c = PriceCache()
    c.update("005930", 75_000)
    c.update("000660", 180_000)
    assert len(c) == 2 and "005930" in c
    assert set(c.get_all()) == {"005930", "000660"}
    c.remove("005930")
    c.remove("005930")  # idempotent
    assert c.get("005930") is None and c.price("005930") is None
    assert "005930" not in c


def test_removed_ticker_restarts_session():
    c = PriceCache()
    c.update("005930", 75_000)
    c.remove("005930")
    assert c.update("005930", 80_000).session_open == 80_000


@pytest.mark.parametrize("bad", [75_000.5, "75000", True, None])
def test_rejects_non_int_prices(bad):
    with pytest.raises(TypeError):
        PriceCache().update("005930", bad)


@pytest.mark.parametrize("bad", [0, -100])
def test_rejects_non_positive_prices(bad):
    with pytest.raises(ValueError):
        PriceCache().update("005930", bad)


def test_concurrent_writers_lose_no_updates():
    c = PriceCache()
    n_threads, n_updates = 8, 2_000

    def writer(i):
        for k in range(n_updates):
            c.update(f"{i:06d}", 1_000 + k)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert c.version == n_threads * n_updates
    assert len(c) == n_threads
    versions = sorted(q.version for q in c.get_all().values())
    assert len(set(versions)) == n_threads
