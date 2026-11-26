"""Tests for app.llm: parsing, mock fixtures, auto-execution, history, persistence, DART."""

from __future__ import annotations

import io
import json
import zipfile
from datetime import date

import pytest

from app.llm import FALLBACK_MESSAGE, MOCK_BUY, MOCK_DEFAULT, dart, handle_chat, parse_llm_output
from app.llm.chat import HISTORY_LIMIT, build_messages
from app.llm.schema import ParseError
from app.services.errors import AlreadyInWatchlistError, NotInWatchlistError, UnknownTickerError


class FakeStore:
    def __init__(self, history=None):
        self.rows = list(history or [])
        self.limit_requested = None

    def recent_chat_messages(self, limit=20):
        self.limit_requested = limit
        return self.rows[-limit:]

    def add_chat_message(self, role, content, actions):
        self.rows.append({"role": role, "content": content, "actions": actions})


class HTTPishError(Exception):
    def __init__(self, detail):
        super().__init__(detail)
        self.detail = detail


class FakeServices:
    def __init__(self, cash=10_000_000, prices=None):
        self.cash = cash
        self.prices = prices or {"005930": 75_400, "035420": 200_000}
        self.held: dict[str, int] = {}
        self.wl = {"005930": "Samsung Electronics"}
        self.calls: list[tuple] = []

    def portfolio(self):
        return {
            "cash_balance": self.cash,
            "total_value": self.cash,
            "positions": [
                {"ticker": t, "name": t, "quantity": q, "avg_cost": 1, "current_price": 1,
                 "market_value": q, "unrealized_pnl": 0, "pnl_pct": 0}
                for t, q in self.held.items()
            ],
        }  # fmt: skip

    async def watchlist(self):
        return [{"ticker": t, "name": n, "price": self.prices.get(t),
                 "session_change_pct": 0.1} for t, n in self.wl.items()]  # fmt: skip

    async def trade(self, ticker, side, quantity):
        self.calls.append(("trade", ticker, side, quantity))
        price = self.prices.get(ticker)
        if price is None:
            return {"success": False, "error": "No price available"}
        if side == "buy":
            if price * quantity > self.cash:
                return {"success": False, "error": "Insufficient cash"}
            self.cash -= price * quantity
            self.held[ticker] = self.held.get(ticker, 0) + quantity
        else:
            if self.held.get(ticker, 0) < quantity:
                return {"success": False, "error": "Insufficient shares"}
            self.cash += price * quantity
            self.held[ticker] -= quantity
        return {"success": True, "ticker": ticker, "side": side, "quantity": quantity,
                "price": price, "cash_balance": self.cash}  # fmt: skip

    async def add_watchlist(self, ticker, name=None):
        self.calls.append(("add", ticker, name))
        if ticker == "999999":
            raise UnknownTickerError("Unknown ticker 999999")
        if ticker == "888888":
            raise HTTPishError("Upstream lookup failed")
        if ticker in self.wl:
            raise AlreadyInWatchlistError(f"{ticker} is already in the watchlist")
        self.wl[ticker] = name or {"035420": "NAVER"}.get(ticker, ticker)
        return {"ticker": ticker, "name": self.wl[ticker], "price": self.prices.get(ticker)}

    async def remove_watchlist(self, ticker):
        self.calls.append(("remove", ticker))
        if ticker not in self.wl:
            raise NotInWatchlistError(f"{ticker} is not in the watchlist")
        del self.wl[ticker]
        return {"ticker": ticker}


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "false")
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    dart._reset_for_tests()


def fake_llm(payload):
    captured: list[list[dict]] = []

    def call(messages):
        captured.append(messages)
        return payload if isinstance(payload, str) else json.dumps(payload)

    call.captured = captured
    return call


# --- parsing -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        '{"message": "hi"}',
        '{"message": "hi", "trades": [], "watchlist_changes": []}',
        '{"message": "hi", "trades": null, "watchlist_changes": null}',
        '```json\n{"message": "hi"}\n```',
        'Sure! {"message": "hi"} hope that helps',
    ],
)
def test_parse_minimal_variants(raw):
    parsed, rejected = parse_llm_output(raw)
    assert parsed.message == "hi" and parsed.trades == [] and parsed.watchlist_changes == []
    assert rejected == []


def test_parse_full():
    parsed, _ = parse_llm_output(
        json.dumps(
            {
                "message": "ok",
                "trades": [{"ticker": "005930", "side": "sell", "quantity": 2}],
                "watchlist_changes": [
                    {"ticker": "035420", "action": "add", "name": "NAVER"},
                    {"ticker": "000270", "action": "remove"},
                ],
            }
        )
    )
    assert parsed.trades[0].side == "sell" and parsed.trades[0].quantity == 2
    assert [c.action for c in parsed.watchlist_changes] == ["add", "remove"]
    assert parsed.watchlist_changes[1].name is None


@pytest.mark.parametrize(
    "raw", ["", "   ", "not json", "[1,2]", '{"trades": []}', '{"message": ""}']
)
def test_parse_rejects_garbage(raw):
    with pytest.raises(ParseError):
        parse_llm_output(raw)


def test_parse_keeps_valid_items_and_rejects_bad_ones():
    parsed, rejected = parse_llm_output(
        json.dumps(
            {
                "message": "m",
                "trades": [
                    {"ticker": "005930", "side": "buy", "quantity": 1},
                    {"ticker": "005930", "side": "hold", "quantity": 1},
                    {"ticker": "005930", "side": "buy", "quantity": 1.5},
                ],
                "watchlist_changes": [{"ticker": "035420", "action": "watch"}],
            }
        )
    )
    assert len(parsed.trades) == 1
    assert [r["kind"] for r in rejected] == ["trade", "trade", "watchlist"]
    assert all(r["success"] is False for r in rejected)


# --- handle_chat ---------------------------------------------------------------------


async def test_executes_trades_and_watchlist_and_persists():
    svc, store = FakeServices(), FakeStore()
    llm = fake_llm(
        {
            "message": "Buying 10 Samsung, adding NAVER.",
            "trades": [{"ticker": "005930", "side": "buy", "quantity": 10}],
            "watchlist_changes": [{"ticker": "035420", "action": "add"}],
        }
    )
    res = await handle_chat("buy 10 samsung", svc, store=store, llm=llm)
    assert res == {
        "message": "Buying 10 Samsung, adding NAVER.",
        "trades": [{"ticker": "005930", "side": "buy", "quantity": 10, "price": 75400,
                    "success": True}],
        "watchlist_changes": [{"ticker": "035420", "action": "add", "name": "NAVER",
                               "success": True}],
    }  # fmt: skip
    assert svc.cash == 10_000_000 - 754_000
    assert [r["role"] for r in store.rows] == ["user", "assistant"]
    assert store.rows[0] == {"role": "user", "content": "buy 10 samsung", "actions": None}
    assert store.rows[1]["actions"] == {
        "trades": res["trades"],
        "watchlist_changes": res["watchlist_changes"],
    }


async def test_trade_failures_are_annotated():
    svc = FakeServices(cash=100_000)
    llm = fake_llm(
        {
            "message": "Trying.",
            "trades": [
                {"ticker": "005930", "side": "buy", "quantity": 100},
                {"ticker": "005930", "side": "sell", "quantity": 1},
                {"ticker": "999999", "side": "buy", "quantity": 1},
                {"ticker": "Samsung", "side": "buy", "quantity": 1},
                {"ticker": "005930", "side": "buy", "quantity": 0},
            ],
            "watchlist_changes": [
                {"ticker": "999999", "action": "add"},
                {"ticker": "888888", "action": "add"},
                {"ticker": "Samsung", "action": "add"},
            ],
        }
    )
    res = await handle_chat("go", svc, store=FakeStore(), llm=llm)
    errors = [t.get("error") for t in res["trades"]]
    assert errors == [
        "Insufficient cash",
        "Insufficient shares",
        "No price available",
        "Invalid ticker",
        "Quantity must be a positive integer",
    ]
    assert all(t["success"] is False and t["price"] is None for t in res["trades"])
    assert [c["error"] for c in res["watchlist_changes"]] == [
        "Unknown ticker 999999",
        "Upstream lookup failed",
        "Invalid ticker",
    ]
    assert all(c["success"] is False for c in res["watchlist_changes"])
    # invalid ticker / qty never reach the service
    assert ("trade", "Samsung", "buy", 1) not in svc.calls
    assert svc.cash == 100_000


async def test_ticker_suffix_normalized():
    svc = FakeServices()
    llm = fake_llm({"message": "x", "trades": [{"ticker": "005930.ks", "side": "buy",
                                                 "quantity": 1}]})  # fmt: skip
    res = await handle_chat("x", svc, store=FakeStore(), llm=llm)
    assert res["trades"][0]["ticker"] == "005930" and res["trades"][0]["success"]


async def test_malformed_output_returns_friendly_message_no_actions():
    svc, store = FakeServices(), FakeStore()
    res = await handle_chat("hello", svc, store=store, llm=fake_llm("I am not JSON"))
    assert res == {"message": FALLBACK_MESSAGE, "trades": [], "watchlist_changes": []}
    assert svc.calls == []
    assert len(store.rows) == 2  # still persisted


async def test_llm_exception_returns_friendly_message():
    def boom(_messages):
        raise RuntimeError("network down")

    res = await handle_chat("hello", FakeServices(), store=FakeStore(), llm=boom)
    assert res["message"] == FALLBACK_MESSAGE and res["trades"] == []


async def test_store_failure_does_not_raise():
    class BadStore:
        def recent_chat_messages(self, limit):
            raise RuntimeError("db")

        def add_chat_message(self, *a):
            raise RuntimeError("db")

    res = await handle_chat("hi", FakeServices(), store=BadStore(), llm=fake_llm({"message": "ok"}))
    assert res["message"] == "ok"


async def test_history_capped_and_prompt_shape():
    history = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
               for i in range(30)]  # fmt: skip
    store = FakeStore(history)
    llm = fake_llm({"message": "ok"})
    await handle_chat("new question", FakeServices(), store=store, llm=llm)
    assert store.limit_requested == HISTORY_LIMIT == 20
    msgs = llm.captured[0]
    assert msgs[0]["role"] == "system" and "FinAlly" in msgs[0]["content"]
    assert "Korean equities" in msgs[0]["content"]
    assert "Cash: ₩10,000,000" in msgs[1]["content"]
    assert "005930 | Samsung Electronics | ₩75,400" in msgs[1]["content"]
    convo = msgs[2:]
    assert len(convo) == 21
    assert convo[0]["content"] == "m10" and convo[-1] == {"role": "user", "content": "new question"}


def test_build_messages_accepts_row_like_objects():
    class Row(dict):
        pass

    msgs = build_messages([Row(role="assistant", content="a"), {"role": "system", "content": "x"}],
                          "ctx", "q")  # fmt: skip
    assert [m["role"] for m in msgs] == ["system", "system", "assistant", "user"]


# --- mock mode -----------------------------------------------------------------------


async def test_mock_default_fixture(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    svc, store = FakeServices(), FakeStore()

    def never(_):
        raise AssertionError("real LLM called in mock mode")

    res = await handle_chat("How is my portfolio?", svc, store=store, llm=never)
    assert res == {"message": MOCK_DEFAULT["message"], "trades": [], "watchlist_changes": []}
    assert svc.calls == [] and len(store.rows) == 2


async def test_mock_buy_fixture_executes(monkeypatch):
    monkeypatch.setenv("LLM_MOCK", "true")
    svc, store = FakeServices(), FakeStore()
    res = await handle_chat("Please BUY something", svc, store=store)
    assert res["message"] == MOCK_BUY["message"]
    assert res["trades"] == [{"ticker": "005930", "side": "buy", "quantity": 1, "price": 75400,
                              "success": True}]  # fmt: skip
    assert res["watchlist_changes"] == [{"ticker": "035420", "action": "add", "name": "NAVER",
                                         "success": True}]  # fmt: skip
    assert svc.held == {"005930": 1} and "035420" in svc.wl
    assert store.rows[1]["actions"]["trades"][0]["success"] is True


# --- OpenDART ------------------------------------------------------------------------


def test_dart_keyword_heuristic():
    assert dart.wants_fundamentals("What was Samsung's revenue last quarter?")
    assert dart.wants_fundamentals("삼성전자 실적 어때?")
    assert dart.wants_fundamentals("Is NAVER's valuation stretched?")
    assert not dart.wants_fundamentals("Buy 10 shares of Kia")


def test_dart_mentioned_tickers():
    known = {"005930": "Samsung Electronics", "035420": "NAVER"}
    got = dart.mentioned_tickers("compare naver with 000660 earnings", known, ["005380"])
    assert got == ["000660", "035420", "005380"]


def _corp_zip() -> bytes:
    xml = (
        "<result><list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>"
        "<stock_code>005930</stock_code></list>"
        "<list><corp_code>99999999</corp_code><stock_code> </stock_code></list></result>"
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", xml.encode())
    return buf.getvalue()


def make_fetcher(calls):
    def fetch(endpoint, params):
        calls.append(endpoint)
        if endpoint == "corpCode.xml":
            return _corp_zip()
        if endpoint == "company.json":
            return json.dumps({"status": "000", "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD",
                               "induty_code": "264", "est_dt": "19690113"}).encode()  # fmt: skip
        if endpoint == "fnlttSinglAcnt.json":
            if params["reprt_code"] != "11012":
                return json.dumps({"status": "013", "message": "no data"}).encode()
            rows = [
                {"fs_div": "OFS", "account_nm": "매출액", "thstrm_amount": "1"},
                {"fs_div": "CFS", "account_nm": "매출액", "thstrm_amount": "74,068,302,000,000"},
                {"fs_div": "CFS", "account_nm": "영업이익", "thstrm_amount": "10,443,878,000,000"},
                {"fs_div": "CFS", "account_nm": "당기순이익", "thstrm_amount": "9,841,345,000,000"},
            ]
            return json.dumps({"status": "000", "list": rows}).encode()
        raise AssertionError(endpoint)

    return fetch


def test_dart_parse_corp_codes():
    assert dart.parse_corp_code_zip(_corp_zip()) == {"005930": "00126380"}


def test_dart_company_summary(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "finally.db"))
    calls: list[str] = []
    s = dart.fetch_company_summary("005930", "k", make_fetcher(calls), today=date(2026, 11, 26))
    assert s["name"] == "Samsung Electronics"
    assert s["period"] == "2026 half-year"
    assert s["financials_krw"] == {"revenue": 74_068_302_000_000,
                                   "operating_profit": 10_443_878_000_000,
                                   "net_income": 9_841_345_000_000}  # fmt: skip
    assert (tmp_path / "dart_corp_codes.json").exists()
    assert dart.fetch_company_summary("123456", "k", make_fetcher(calls)) is None


async def test_dart_enrichment_cached_and_gated(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "finally.db"))
    calls: list[str] = []
    fetch = make_fetcher(calls)
    known = {"005930": "Samsung Electronics"}

    assert await dart.enrichment("Samsung Electronics revenue?", known, [], fetch) is None  # no key
    monkeypatch.setenv("OPENDART_API_KEY", "k")
    assert await dart.enrichment("buy samsung", known, [], fetch) is None  # no keyword
    assert calls == []

    out = await dart.enrichment("Samsung Electronics revenue?", known, [], fetch)
    assert "005930 Samsung Electronics —" in out and "revenue ₩74,068,302,000,000" in out
    n = len(calls)
    await dart.enrichment("samsung electronics profit?", known, [], fetch)
    assert len(calls) == n  # 24h cache hit


async def test_dart_failures_swallowed(monkeypatch):
    monkeypatch.setenv("OPENDART_API_KEY", "k")

    def broken(endpoint, params):
        raise OSError("offline")

    assert await dart.enrichment("005930 earnings", {}, [], broken) is None


async def test_dart_context_reaches_llm(monkeypatch):
    monkeypatch.setenv("OPENDART_API_KEY", "k")

    async def fake_enrichment(message, names, held):
        return "COMPANY FUNDAMENTALS (OpenDART, KRW):\n- 005930 X"

    monkeypatch.setattr(dart, "enrichment", fake_enrichment)
    llm = fake_llm({"message": "ok"})
    await handle_chat("samsung earnings?", FakeServices(), store=FakeStore(), llm=llm)
    assert "COMPANY FUNDAMENTALS" in llm.captured[0][1]["content"]


async def test_dart_resolve_name(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "finally.db"))
    calls: list[str] = []
    assert await dart.resolve_name("005930", make_fetcher(calls)) is None  # no key
    monkeypatch.setenv("OPENDART_API_KEY", "k")
    assert await dart.resolve_name("005930", make_fetcher(calls)) == "Samsung Electronics"
    assert await dart.resolve_name("123456", make_fetcher(calls)) is None


async def test_end_to_end_mock_via_app(monkeypatch, tmp_path):
    """Real PortfolioService + real DB through POST /api/chat in mock mode."""
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.setenv("DB_PATH", str(tmp_path / "finally.db"))
    monkeypatch.setenv("SIM_SEED", "42")
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app()) as client:
        r = client.post("/api/chat", json={"message": "hello"})
        assert r.status_code == 200
        assert r.json() == {"message": MOCK_DEFAULT["message"], "trades": [],
                            "watchlist_changes": []}  # fmt: skip
        r = client.post("/api/chat", json={"message": "buy please"})
        body = r.json()
        assert body["trades"][0]["success"] is True and body["trades"][0]["price"] > 0
        # NAVER is already a default watchlist ticker → idempotent success in chat
        assert body["watchlist_changes"] == [
            {"ticker": "035420", "action": "add", "name": "NAVER", "success": True}
        ]
        # REST keeps its 409 for the same duplicate
        assert client.post("/api/watchlist", json={"ticker": "035420"}).status_code == 409
        positions = client.get("/api/portfolio").json()["positions"]
        assert [p["ticker"] for p in positions] == ["005930"]


async def test_watchlist_changes_idempotent_in_chat():
    """Adding an already-watched / removing an unwatched ticker is a no-op success."""
    svc = FakeServices()
    llm = fake_llm(
        {
            "message": "ok",
            "watchlist_changes": [
                {"ticker": "005930", "action": "add"},
                {"ticker": "000270", "action": "remove"},
            ],
        }
    )
    res = await handle_chat("go", svc, store=FakeStore(), llm=llm)
    assert res["watchlist_changes"] == [
        {"ticker": "005930", "action": "add", "name": "Samsung Electronics", "success": True},
        {"ticker": "000270", "action": "remove", "success": True},
    ]
    assert svc.wl == {"005930": "Samsung Electronics"}


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("SAMSUNG ELECTRONICS CO,.LTD", "Samsung Electronics"),
        ("SAMSUNG ELECTRONICS CO., LTD.", "Samsung Electronics"),
        ("SK hynix Inc.", "SK hynix"),
        ("SK HYNIX INC.", "SK Hynix"),
        ("NAVER Corporation", "NAVER"),
        ("NAVER CORP.", "NAVER"),
        ("KIA CORPORATION", "Kia"),
        ("POSCO HOLDINGS INC.", "POSCO Holdings"),
        ("HYUNDAI MOTOR COMPANY", "Hyundai Motor"),
        ("LG ENERGY SOLUTION, LTD.", "LG Energy Solution"),
        ("Celltrion, Inc.", "Celltrion"),
        ("Samsung Biologics Co., Ltd.", "Samsung Biologics"),
        ("KAKAO CORP.", "Kakao"),
        ("SK TELECOM CO.,LTD", "SK Telecom"),
        ("", None),
    ],
)
def test_dart_display_name(raw, expected):
    assert dart.display_name(raw) == expected
