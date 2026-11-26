"""Unit tests for the SQLite layer (app.db)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import UTC, datetime

import pytest

from app import db
from app.market.seed_data import DEFAULT_TICKERS, SEED_PARAMS


@pytest.fixture
def path(tmp_path):
    return tmp_path / "nested" / "finally.db"


# ---------------------------------------------------------------- init / seed


def test_init_creates_parent_dir_tables_and_seed(path):
    db.init_db(path)
    assert path.exists()
    assert db.get_cash(path=path) == 10_000_000.0
    wl = db.list_watchlist(path=path)
    assert [w["ticker"] for w in wl] == list(DEFAULT_TICKERS)
    assert wl[0]["name"] == SEED_PARAMS["005930"].name
    conn = db.connect(path)
    try:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        indexes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
        assert isinstance(conn.execute("SELECT 1 AS x").fetchone(), sqlite3.Row)
    finally:
        conn.close()
    assert {
        "portfolio_state",
        "watchlist",
        "positions",
        "trades",
        "portfolio_snapshots",
        "chat_messages",
    } <= tables
    assert {
        "idx_trades_executed_at",
        "idx_trades_ticker",
        "idx_snapshots_recorded_at",
        "idx_chat_created_at",
    } <= indexes


def test_init_is_idempotent_and_does_not_reseed_removed(path):
    db.init_db(path)
    assert db.remove_watchlist("005930", path=path)
    db.execute_trade("000660", "buy", 1, 180_000, path=path)
    db.init_db(path)
    db.init_db(path)
    assert "005930" not in db.watchlist_tickers(path=path)
    assert len(db.list_watchlist(path=path)) == 9
    assert db.get_cash(path=path) == 10_000_000.0 - 180_000


def test_lazy_init_on_first_use(path):
    # No explicit init_db: any repository call initializes the database.
    assert db.get_cash(path=path) == 10_000_000.0


def test_lazy_init_recovers_after_file_deleted(path):
    db.init_db(path)
    for suffix in ("", "-wal", "-shm"):
        p = path.with_name(path.name + suffix)
        if p.exists():
            p.unlink()
    assert len(db.list_watchlist(path=path)) == 10


def test_db_path_env(tmp_path, monkeypatch):
    target = tmp_path / "env" / "x.db"
    monkeypatch.setenv("DB_PATH", str(target))
    assert db.get_db_path() == target
    assert db.get_cash() == 10_000_000.0
    assert target.exists()


def test_default_path_is_repo_db():
    assert db.DEFAULT_DB_PATH.parts[-2:] == ("db", "finally.db")
    assert (db.DEFAULT_DB_PATH.parent.parent / "backend").is_dir()


# ---------------------------------------------------------------- watchlist


def test_watchlist_add_remove(path):
    assert db.add_watchlist("247540", "EcoPro BM", path=path) is True
    assert db.add_watchlist("247540", "EcoPro BM", path=path) is False
    assert db.watchlist_tickers(path=path)[-1] == "247540"
    assert db.remove_watchlist("247540", path=path) is True
    assert db.remove_watchlist("247540", path=path) is False


# ---------------------------------------------------------------- trading


def test_buy_opens_position_and_logs(path):
    r = db.execute_trade("005930", "buy", 10, 75_000, path=path)
    assert r.success and r.error is None and r.opened and not r.closed
    assert r.cash_balance == 10_000_000 - 750_000
    assert r.total_value == 10_000_000
    assert db.get_cash(path=path) == r.cash_balance
    pos = db.get_position("005930", path=path)
    assert pos["quantity"] == 10 and pos["avg_cost"] == 75_000
    trades = db.list_trades(path=path)
    assert len(trades) == 1
    assert trades[0] | {"id": None, "executed_at": None} == {
        "id": None,
        "ticker": "005930",
        "side": "buy",
        "quantity": 10,
        "price": 75_000.0,
        "executed_at": None,
    }
    assert r.to_response() == {
        "success": True,
        "ticker": "005930",
        "side": "buy",
        "quantity": 10,
        "price": 75_000,
        "cash_balance": 9_250_000,
    }


def test_weighted_average_cost(path):
    db.execute_trade("005930", "buy", 10, 70_000, path=path)
    r = db.execute_trade("005930", "buy", 30, 80_000, path=path)
    assert not r.opened
    pos = db.get_position("005930", path=path)
    assert pos["quantity"] == 40
    assert pos["avg_cost"] == pytest.approx((10 * 70_000 + 30 * 80_000) / 40)


def test_sell_keeps_avg_cost_and_deletes_at_zero(path):
    db.execute_trade("005930", "buy", 10, 70_000, path=path)
    r = db.execute_trade("005930", "sell", 4, 80_000, path=path)
    assert r.success and not r.closed
    pos = db.get_position("005930", path=path)
    assert pos["quantity"] == 6 and pos["avg_cost"] == 70_000
    r = db.execute_trade("005930", "sell", 6, 80_000, path=path)
    assert r.success and r.closed
    assert db.get_position("005930", path=path) is None
    assert db.position_tickers(path=path) == []
    assert db.get_cash(path=path) == 10_000_000 - 700_000 + 800_000


def test_insufficient_cash_writes_nothing(path):
    r = db.execute_trade("207940", "buy", 13, 800_000, path=path)
    assert not r.success and r.error == "Insufficient cash"
    assert r.cash_balance == 10_000_000
    assert r.to_response() == {"success": False, "error": "Insufficient cash"}
    assert db.list_positions(path=path) == []
    assert db.list_trades(path=path) == []
    assert db.list_snapshots(path=path) == []


def test_exact_cash_buy_allowed(path):
    r = db.execute_trade("207940", "buy", 12, 800_000, path=path)
    assert r.success
    r = db.execute_trade("005930", "buy", 5, 80_000, path=path)
    assert r.success and r.cash_balance == 0


def test_insufficient_shares(path):
    r = db.execute_trade("005930", "sell", 1, 75_000, path=path)
    assert r.error == "Insufficient shares"
    db.execute_trade("005930", "buy", 2, 75_000, path=path)
    r = db.execute_trade("005930", "sell", 3, 75_000, path=path)
    assert r.error == "Insufficient shares"
    assert db.get_position("005930", path=path)["quantity"] == 2


@pytest.mark.parametrize(
    ("side", "qty", "price", "err"),
    [
        ("hold", 1, 100, "Invalid side"),
        ("buy", 0, 100, "Invalid quantity"),
        ("buy", 1.5, 100, "Invalid quantity"),
        ("buy", True, 100, "Invalid quantity"),
        ("buy", 1, 0, "Invalid price"),
    ],
)
def test_invalid_inputs(path, side, qty, price, err):
    r = db.execute_trade("005930", side, qty, price, path=path)
    assert not r.success and r.error == err
    assert r.cash_balance == 10_000_000


def test_snapshot_uses_lookup_then_avg_cost(path):
    db.execute_trade("005930", "buy", 10, 70_000, path=path)
    db.execute_trade("000660", "buy", 1, 180_000, path=path)
    prices = {"005930": 75_000}
    r = db.execute_trade("035720", "buy", 2, 40_000, prices.get, path=path)
    cash = 10_000_000 - 700_000 - 180_000 - 80_000
    # 005930 from lookup, 000660 falls back to avg cost, 035720 at fill price.
    assert r.total_value == cash + 10 * 75_000 + 180_000 + 80_000
    assert db.list_snapshots(path=path)[-1]["total_value"] == r.total_value


def test_lookup_errors_fall_back(path):
    db.execute_trade("005930", "buy", 1, 70_000, path=path)

    def boom(_t):
        raise RuntimeError

    r = db.execute_trade("000660", "buy", 1, 180_000, boom, path=path)
    assert r.success and r.total_value == 10_000_000


def test_concurrent_buys_cannot_overdraw(path):
    db.init_db(path)
    results = []
    barrier = threading.Barrier(20)

    def worker():
        barrier.wait()
        results.append(db.execute_trade("207940", "buy", 1, 800_000, path=path))

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    ok = [r for r in results if r.success]
    assert len(ok) == 12
    assert all(r.error == "Insufficient cash" for r in results if not r.success)
    assert db.get_cash(path=path) == 10_000_000 - 12 * 800_000 >= 0
    assert db.get_position("207940", path=path)["quantity"] == 12
    assert len(db.list_trades(100, path=path)) == 12
    assert sum(r.opened for r in ok) == 1


# ---------------------------------------------------------------- snapshots


def test_snapshots(path):
    assert db.last_snapshot_time(path=path) is None
    for v in (1.0, 2.0, 3.0):
        db.record_snapshot(v, path=path)
    snaps = db.list_snapshots(path=path)
    assert [s["total_value"] for s in snaps] == [1.0, 2.0, 3.0]
    assert [s["total_value"] for s in db.list_snapshots(2, path=path)] == [2.0, 3.0]
    t = db.last_snapshot_time(path=path)
    assert t.tzinfo is not None
    assert abs((datetime.now(UTC) - t).total_seconds()) < 5
    assert snaps[0]["recorded_at"].endswith("Z")


# ---------------------------------------------------------------- chat


def test_chat_round_trip(path):
    actions = {
        "trades": [
            {"ticker": "005930", "side": "buy", "quantity": 1, "price": 75_000, "success": True}
        ],
        "watchlist_changes": [
            {"ticker": "035420", "action": "add", "name": "네이버", "success": True}
        ],
    }
    db.add_chat_message("user", "Buy 1 Samsung", path=path)
    mid = db.add_chat_message("assistant", "Done.", actions, path=path)
    msgs = db.recent_chat_messages(path=path)
    assert [m["role"] for m in msgs] == ["user", "assistant"]
    assert msgs[0]["actions"] is None
    assert msgs[1]["id"] == mid and msgs[1]["actions"] == actions


def test_chat_recent_limit_oldest_first(path):
    for i in range(25):
        db.add_chat_message("user", f"m{i}", path=path)
    msgs = db.recent_chat_messages(path=path)
    assert len(msgs) == 20
    assert [m["content"] for m in msgs] == [f"m{i}" for i in range(5, 25)]


def test_chat_role_constraint(path):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_chat_message("system", "x", path=path)
