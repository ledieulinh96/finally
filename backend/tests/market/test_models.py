"""PriceQuote semantics and the PLAN §6 SSE payload shape."""

from datetime import UTC, datetime

from app.market.models import PriceQuote

TS = datetime(2026, 11, 13, 9, 30, 1, 234000, tzinfo=UTC)


def quote(price=75_400, prev=75_200, open_=74_800):
    return PriceQuote("005930", price, prev, open_, TS, 7)


def test_direction():
    assert quote(75_400, 75_200).direction == "up"
    assert quote(75_000, 75_200).direction == "down"
    assert quote(75_200, 75_200).direction == "flat"


def test_change_and_session_change_pct():
    q = quote()
    assert q.change == 200
    assert q.session_change_pct == 0.80
    assert quote(open_=0).session_change_pct == 0.0


def test_to_event_matches_plan_shape_exactly():
    assert quote().to_event("Samsung Electronics") == {
        "ticker": "005930",
        "name": "Samsung Electronics",
        "price": 75400,
        "prev_price": 75200,
        "session_open": 74800,
        "session_change_pct": 0.80,
        "direction": "up",
        "timestamp": "2026-11-13T09:30:01.234Z",
    }


def test_quote_is_immutable():
    q = quote()
    try:
        q.price = 1  # type: ignore[misc]
    except AttributeError:
        return
    raise AssertionError("PriceQuote should be frozen")
