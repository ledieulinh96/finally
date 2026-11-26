"""REST routes: status codes and response shapes per PLAN §8."""

from __future__ import annotations

import pytest

from app.market import DEFAULT_TICKERS

POSITION_KEYS = {
    "ticker",
    "name",
    "quantity",
    "avg_cost",
    "current_price",
    "market_value",
    "unrealized_pnl",
    "pnl_pct",
}
WATCH_KEYS = {
    "ticker",
    "name",
    "price",
    "prev_price",
    "session_open",
    "session_change_pct",
    "direction",
}


def buy(client, ticker="005930", qty=5, side="buy"):
    return client.post(
        "/api/portfolio/trade", json={"ticker": ticker, "quantity": qty, "side": side}
    )


# ------------------------------------------------------------------- portfolio
def test_initial_portfolio(client):
    r = client.get("/api/portfolio")
    assert r.status_code == 200
    body = r.json()
    assert body == {"cash_balance": 10_000_000, "total_value": 10_000_000, "positions": []}


def test_buy_then_portfolio(app, client):
    price = app.state.price_cache.price("005930")
    r = buy(client)
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["ticker"] == "005930" and body["side"] == "buy" and body["quantity"] == 5
    assert isinstance(body["price"], int) and body["price"] > 0
    assert body["cash_balance"] == 10_000_000 - 5 * body["price"]
    assert abs(body["price"] - price) <= price * 0.05

    p = client.get("/api/portfolio").json()
    assert len(p["positions"]) == 1
    pos = p["positions"][0]
    assert set(pos) == POSITION_KEYS
    assert pos["name"] == "Samsung Electronics"
    assert pos["quantity"] == 5
    assert pos["market_value"] == 5 * pos["current_price"]
    assert p["total_value"] == p["cash_balance"] + pos["market_value"]


def test_sell_all_deletes_position(client):
    buy(client, qty=3)
    r = buy(client, qty=3, side="sell")
    assert r.status_code == 200 and r.json()["success"] is True
    assert client.get("/api/portfolio").json()["positions"] == []


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"ticker": "005930", "quantity": 10_000, "side": "buy"}, "Insufficient cash"),
        ({"ticker": "005930", "quantity": 1, "side": "sell"}, "Insufficient shares"),
        ({"ticker": "bad!", "quantity": 1, "side": "buy"}, "Invalid ticker"),
    ],
)
def test_trade_business_failures_are_400(client, payload, error):
    r = client.post("/api/portfolio/trade", json=payload)
    assert r.status_code == 400
    assert r.json() == {"success": False, "error": error}


@pytest.mark.parametrize(
    "payload",
    [
        {"ticker": "005930", "quantity": 1.5, "side": "buy"},
        {"ticker": "005930", "quantity": 0, "side": "buy"},
        {"ticker": "005930", "quantity": -1, "side": "buy"},
        {"ticker": "005930", "quantity": 1, "side": "short"},
        {"ticker": "005930"},
    ],
)
def test_trade_malformed_is_422(client, payload):
    assert client.post("/api/portfolio/trade", json=payload).status_code == 422


def test_trade_ticker_suffix_and_case(client):
    r = buy(client, ticker=" 005930.ks ", qty=1)
    assert r.status_code == 200 and r.json()["ticker"] == "005930"


def test_buy_off_watchlist_tracks_ticker(app, client):
    r = buy(client, ticker="247540", qty=1)
    assert r.status_code == 200, r.text
    assert "247540" in app.state.market_source.tickers
    names = {p["ticker"]: p["name"] for p in client.get("/api/portfolio").json()["positions"]}
    assert "247540" in names
    # Selling everything un-tracks it again (not watched, not held).
    assert buy(client, ticker="247540", qty=1, side="sell").status_code == 200
    assert "247540" not in app.state.market_source.tickers


def test_history_has_snapshot_after_trade(client):
    buy(client, qty=1)
    r = client.get("/api/portfolio/history")
    assert r.status_code == 200
    rows = r.json()
    assert rows and set(rows[-1]) == {"total_value", "recorded_at"}
    before = len(client.get("/api/portfolio/history").json())
    assert len(client.get("/api/portfolio/history").json()) == before  # read-only


# ------------------------------------------------------------------- watchlist
def test_get_watchlist(client):
    r = client.get("/api/watchlist")
    assert r.status_code == 200
    rows = r.json()
    assert [row["ticker"] for row in rows] == list(DEFAULT_TICKERS)
    for row in rows:
        assert set(row) == WATCH_KEYS
        assert isinstance(row["price"], int)
        assert row["direction"] in {"up", "down", "flat"}


def test_add_and_remove_watchlist(app, client):
    r = client.post("/api/watchlist", json={"ticker": "247540"})
    assert r.status_code == 201
    body = r.json()
    assert body["ticker"] == "247540"
    assert body["name"] and body["name"] != "247540"  # from krx_listing.csv
    assert isinstance(body["price"], int)
    assert "247540" in app.state.market_source.tickers
    assert "247540" in [w["ticker"] for w in client.get("/api/watchlist").json()]

    assert client.post("/api/watchlist", json={"ticker": "247540"}).status_code == 409

    r = client.delete("/api/watchlist/247540")
    assert r.status_code == 200
    assert "247540" not in app.state.market_source.tickers
    assert client.delete("/api/watchlist/247540").status_code == 404


def test_add_watchlist_with_explicit_name(client):
    r = client.post("/api/watchlist", json={"ticker": "123456", "name": "Custom Co"})
    assert r.status_code == 201
    assert r.json()["name"] == "Custom Co"


def test_watchlist_invalid_ticker_422(client):
    r = client.post("/api/watchlist", json={"ticker": "12"})
    assert r.status_code == 422 and "detail" in r.json()
    assert client.delete("/api/watchlist/abc").status_code == 422


def test_removed_but_held_keeps_price(app, client):
    buy(client, ticker="035720", qty=2)
    assert client.delete("/api/watchlist/035720").status_code == 200
    assert "035720" in app.state.market_source.tickers
    pos = client.get("/api/portfolio").json()["positions"][0]
    assert pos["name"] == "Kakao"


# ------------------------------------------------------------------------ chat
def test_chat_mock_plain(client):
    r = client.post("/api/chat", json={"message": "How is my portfolio?"})
    assert r.status_code == 200
    body = r.json()
    assert body["message"].startswith("Your portfolio looks well-diversified")
    assert body["trades"] == [] and body["watchlist_changes"] == []
    assert client.get("/api/portfolio").json()["positions"] == []


def test_chat_mock_buy_executes(client):
    # NAVER is a default; remove it first so the fixture's add succeeds.
    client.delete("/api/watchlist/035420")
    r = client.post("/api/chat", json={"message": "Please BUY something"})
    assert r.status_code == 200
    body = r.json()
    assert body["trades"][0]["ticker"] == "005930"
    assert body["trades"][0]["success"] is True
    assert body["watchlist_changes"][0]["ticker"] == "035420"
    assert body["watchlist_changes"][0]["success"] is True
    p = client.get("/api/portfolio").json()
    assert [x["ticker"] for x in p["positions"]] == ["005930"]
    assert p["cash_balance"] < 10_000_000
    assert "035420" in [w["ticker"] for w in client.get("/api/watchlist").json()]


def test_chat_mock_buy_with_naver_already_watched(client):
    r = client.post("/api/chat", json={"message": "buy"})
    assert r.status_code == 200
    body = r.json()
    assert body["trades"][0]["success"] is True
    change = body["watchlist_changes"][0]
    # Chat treats "already watched" as success (desired state holds).
    assert change["ticker"] == "035420" and change["success"] is True
    assert [w["ticker"] for w in client.get("/api/watchlist").json()].count("035420") == 1


@pytest.mark.parametrize("message", ["", "x" * 2001])
def test_chat_validation_422(client, message):
    assert client.post("/api/chat", json={"message": message}).status_code == 422


def test_chat_whitespace_only_422(client):
    assert client.post("/api/chat", json={"message": "   "}).status_code == 422


def test_chat_history(client):
    assert client.get("/api/chat/history").json() == []
    client.post("/api/chat", json={"message": "hello"})
    client.post("/api/chat", json={"message": "buy"})
    r = client.get("/api/chat/history")
    assert r.status_code == 200
    rows = r.json()
    assert [m["role"] for m in rows] == ["user", "assistant", "user", "assistant"]
    for m in rows:
        assert set(m) == {"id", "role", "content", "trades", "watchlist_changes", "created_at"}
    assert rows[0]["content"] == "hello" and rows[0]["trades"] == []
    assert rows[3]["trades"][0]["ticker"] == "005930"
    assert rows[3]["watchlist_changes"][0]["ticker"] == "035420"


def test_chat_history_capped_at_50(app, client):
    from app import db

    path = app.state.services.db_path
    for i in range(60):
        db.add_chat_message("user", f"m{i}", path=path)
    rows = client.get("/api/chat/history").json()
    assert len(rows) == 50
    assert rows[0]["content"] == "m10" and rows[-1]["content"] == "m59"
