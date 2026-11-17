from datetime import UTC, datetime

import pytest

from app.market.models import PriceQuote
from app.market.seed import InvalidTickerError, normalize_ticker, params_for
from app.market.ticks import snap_down, snap_to_tick, snap_up, tick_size


def q(price=75400, prev=75200, open_=74800):
    return PriceQuote("005930", price, prev, open_, datetime(2026, 11, 13, 9, 30, 1, 234000, UTC), 7)


def test_direction():
    assert q(75400, 75200).direction == "up"
    assert q(75000, 75200).direction == "down"
    assert q(75200, 75200).direction == "flat"


def test_session_change_pct_rounded():
    assert q().session_change_pct == 0.8
    assert q(open_=0).session_change_pct == 0.0


def test_to_event_matches_plan_shape():
    e = q().to_event("Samsung Electronics")
    assert e == {
        "ticker": "005930", "name": "Samsung Electronics", "price": 75400, "prev_price": 75200,
        "session_open": 74800, "session_change_pct": 0.8, "direction": "up",
        "timestamp": "2026-11-13T09:30:01.234Z",
    }  # fmt: skip


@pytest.mark.parametrize(
    "price,tick",
    [(1999, 1), (2000, 5), (4999, 5), (5000, 10), (19999, 10), (20000, 50), (49999, 50),
     (50000, 100), (199999, 100), (200000, 500), (499999, 500), (500000, 1000), (9e6, 1000)],
)  # fmt: skip
def test_tick_size_table(price, tick):
    assert tick_size(price) == tick


def test_snapping():
    assert snap_to_tick(75037) == 75000
    assert snap_to_tick(75060) == 75100
    assert snap_down(75099) == 75000
    assert snap_up(75001) == 75100
    assert snap_to_tick(0.2) == 1  # minimum one tick
    assert isinstance(snap_to_tick(75037.4), int)


def test_normalize_ticker():
    assert normalize_ticker(" 005930 ") == "005930"
    assert normalize_ticker("00593a") == "00593A"
    for bad in ["", "5930", "0059300", "AAPL", "00593;", None]:
        with pytest.raises(InvalidTickerError):
            normalize_ticker(bad)


def test_params_for_unknown_is_deterministic_and_tick_aligned():
    a, b = params_for("123456"), params_for("123456")
    assert a == b and a.sector == "other"
    assert 5_000 <= a.seed_price <= 500_000
    assert a.seed_price % tick_size(a.seed_price) == 0
    assert params_for("005930").seed_price == 75_000
