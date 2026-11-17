"""KRX session clock."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.market.market_hours import KST, is_market_open, market_session


def kst(h, m, day=13):  # 2026-11-13 is a Friday
    return datetime(2026, 11, day, h, m, tzinfo=KST)


@pytest.mark.parametrize(
    ("when", "session"),
    [
        (kst(8, 0), "closed"),
        (kst(8, 30), "pre_open"),
        (kst(8, 59), "pre_open"),
        (kst(9, 0), "regular"),
        (kst(15, 19), "regular"),
        (kst(15, 20), "closing_auction"),
        (kst(15, 30), "after_hours"),
        (kst(19, 59), "after_hours"),
        (kst(20, 0), "closed"),
        (kst(12, 0, day=14), "closed"),
        (kst(12, 0, day=15), "closed"),  # weekend
    ],
)
def test_sessions(when, session):
    assert market_session(when) == session


def test_converts_from_other_timezones():
    assert market_session(datetime(2026, 11, 13, 1, 0, tzinfo=UTC)) == "regular"  # 10:00 KST
    ny = timezone(timedelta(hours=-5))
    assert market_session(datetime(2026, 11, 12, 20, 0, tzinfo=ny)) == "regular"  # 10:00 KST Fri


def test_is_market_open():
    assert is_market_open(kst(10, 0)) and is_market_open(kst(15, 25))
    assert not is_market_open(kst(16, 0))


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        market_session(datetime(2026, 11, 13, 10, 0))


def test_default_now_works():
    assert market_session() in {"pre_open", "regular", "closing_auction", "after_hours", "closed"}
