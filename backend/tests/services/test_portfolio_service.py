"""PortfolioService unit tests (no HTTP)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app import db
from app.services import (
    AlreadyInWatchlistError,
    InvalidTickerError,
    NotInWatchlistError,
    UnknownTickerError,
)
from app.services.portfolio import _num


@pytest.fixture
def services(app, client):
    return app.state.services


def call(client, fn, *args, **kwargs):
    async def go():
        return await fn(*args, **kwargs)

    return client.portal.call(go)


def test_num_helper():
    assert _num(75400.0) == 75400 and isinstance(_num(75400.0), int)
    assert _num(74333.3333) == 74333.33


def test_trade_validation(client, services):
    assert call(client, services.trade, "005930", "buy", 0) == {
        "success": False,
        "error": "Invalid quantity",
    }
    assert call(client, services.trade, "005930", "buy", 1.0)["error"] == "Invalid quantity"
    assert call(client, services.trade, "005930", "buy", True)["error"] == "Invalid quantity"
    assert call(client, services.trade, "005930", "hold", 1)["error"] == "Invalid side"
    assert call(client, services.trade, "nope", "buy", 1)["error"] == "Invalid ticker"


def test_no_price_available(client, services, monkeypatch):
    async def refuse(ticker):
        return False

    monkeypatch.setattr(services.source, "add_ticker", refuse)
    r = call(client, services.trade, "999999", "buy", 1)
    assert r == {"success": False, "error": "No price available"}


def test_weighted_avg_cost(client, services):
    cache = services.cache
    cache.update("005930", 70000)
    call(client, services.trade, "005930", "buy", 10)
    # Stop the simulator from overwriting our test price between calls.
    call(client, services.source.stop)
    cache.update("005930", 80000)
    r = call(client, services.trade, "005930", "buy", 10)
    assert r["price"] == 80000
    p = call(client, services.portfolio)
    pos = p["positions"][0]
    assert pos["quantity"] == 20
    assert pos["current_price"] == 80000
    assert pos["unrealized_pnl"] == (80000 - pos["avg_cost"]) * 20
    assert pos["pnl_pct"] == round((80000 - pos["avg_cost"]) / pos["avg_cost"] * 100, 2)


def test_unpriced_position_falls_back_to_avg_cost(client, services):
    call(client, services.trade, "005930", "buy", 2)
    call(client, services.source.stop)
    services.cache.remove("005930")
    pos = call(client, services.portfolio)["positions"][0]
    assert pos["current_price"] == pos["avg_cost"]
    assert pos["unrealized_pnl"] == 0 and pos["pnl_pct"] == 0


def test_unpriced_watchlist_row(client, services):
    call(client, services.source.stop)
    services.cache.remove("005930")
    row = next(w for w in call(client, services.watchlist) if w["ticker"] == "005930")
    assert row["price"] is None and row["prev_price"] is None and row["session_open"] is None
    assert row["direction"] == "flat"


def test_watchlist_errors(client, services, monkeypatch):
    with pytest.raises(InvalidTickerError):
        call(client, services.add_watchlist, "x")
    with pytest.raises(AlreadyInWatchlistError):
        call(client, services.add_watchlist, "005930")
    with pytest.raises(NotInWatchlistError):
        call(client, services.remove_watchlist, "111111")

    async def refuse(ticker):
        return False

    monkeypatch.setattr(services.source, "add_ticker", refuse)
    with pytest.raises(UnknownTickerError):
        call(client, services.add_watchlist, "999999")
    assert "999999" not in db.watchlist_tickers(path=services.db_path)


def test_name_resolver_used_when_unknown(client, services):
    async def resolver(ticker):
        return "Resolved Corp" if ticker == "999998" else None

    services.add_name_resolver(resolver)
    r = call(client, services.add_watchlist, "999998")
    assert r["name"] == "Resolved Corp"
    assert services.name("999998") == "Resolved Corp"


def test_failing_resolver_falls_back_to_code(client, services):
    async def boom(ticker):
        raise RuntimeError("down")

    services.add_name_resolver(boom)
    assert call(client, services.add_watchlist, "999997")["name"] == "999997"


def test_snapshot_if_due(client, services):
    path = services.db_path
    # The lifespan took a startup snapshot, so a 60 s check is skipped.
    assert len(db.list_snapshots(path=path)) == 1
    assert call(client, services.snapshot_if_due) is False
    n = len(db.list_snapshots(path=path))
    assert call(client, services.snapshot_if_due, 0.0) is True
    assert len(db.list_snapshots(path=path)) == n + 1
    last = db.last_snapshot_time(path=path)
    assert datetime.now(UTC) - last < timedelta(seconds=5)


def test_run_snapshots_loop(client, services):
    """The loop records once the interval elapses."""
    import asyncio

    path = services.db_path
    n = len(db.list_snapshots(path=path))

    async def go():
        task = asyncio.create_task(services.run_snapshots(0.05))
        await asyncio.sleep(0.3)
        task.cancel()

    client.portal.call(go)
    # min delay is 1 s after the first record, so exactly one extra snapshot.
    assert len(db.list_snapshots(path=path)) == n + 1
