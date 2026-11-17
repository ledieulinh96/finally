"""SSE: frame format, initial snapshot, deltas, resume, keepalive, disconnect."""

import asyncio
import json

from fastapi import FastAPI

from app.market.cache import PriceCache
from app.market.names import NameRegistry
from app.market.stream import create_stream_router, parse_last_event_id, price_events


def parse_frames(chunks):
    events, comments = [], []
    for frame in "".join(chunks).split("\n\n"):
        if not frame.strip():
            continue
        if frame.startswith(":"):
            comments.append(frame)
            continue
        fields = dict(line.split(": ", 1) for line in frame.split("\n"))
        events.append(fields)
    return events, comments


def disconnect_after(n):
    calls = {"n": 0}

    async def is_disconnected():
        calls["n"] += 1
        return calls["n"] > n

    return is_disconnected


async def collect(gen):
    return [chunk async for chunk in gen]


async def test_initial_snapshot_then_only_changes():
    cache = PriceCache()
    cache.update("005930", 75_000)
    cache.update("000660", 180_000)
    names = NameRegistry()
    state = {"n": 0}

    async def is_disconnected():
        state["n"] += 1
        if state["n"] == 2:  # between loop iterations, one ticker moves
            cache.update("005930", 75_100)
        return state["n"] > 3

    chunks = await collect(price_events(cache, names, is_disconnected, interval=0.001))
    assert chunks[0] == "retry: 2000\n\n"
    events, _ = parse_frames(chunks[1:])
    tickers = [json.loads(e["data"])["ticker"] for e in events]
    assert tickers == ["005930", "000660", "005930"]
    ids = [int(e["id"]) for e in events]
    assert ids == sorted(ids) and ids[-1] == cache.version
    last = json.loads(events[-1]["data"])
    assert last["name"] == "Samsung Electronics"
    assert (last["price"], last["prev_price"], last["direction"]) == (75_100, 75_000, "up")
    assert set(last) == {
        "ticker",
        "name",
        "price",
        "prev_price",
        "session_open",
        "session_change_pct",
        "direction",
        "timestamp",
    }


async def test_resume_from_last_event_id_sends_only_missed():
    cache = PriceCache()
    cache.update("005930", 75_000)
    v = cache.version
    cache.update("000660", 180_000)
    chunks = await collect(
        price_events(cache, NameRegistry(), disconnect_after(1), since=v, interval=0.001)
    )
    events, _ = parse_frames(chunks[1:])
    assert [json.loads(e["data"])["ticker"] for e in events] == ["000660"]


async def test_keepalive_when_idle():
    chunks = await collect(
        price_events(
            PriceCache(), NameRegistry(), disconnect_after(10), interval=0.001, keepalive=0.003
        )
    )
    events, comments = parse_frames(chunks[1:])
    assert events == [] and comments.count(": keepalive") >= 2


async def test_unknown_ticker_name_falls_back_to_code():
    cache = PriceCache()
    cache.update("900111", 3_335)
    chunks = await collect(price_events(cache, NameRegistry(), disconnect_after(1), interval=0.001))
    events, _ = parse_frames(chunks[1:])
    assert json.loads(events[0]["data"])["name"] == "900111"


def test_parse_last_event_id():
    assert parse_last_event_id(None, 10) == 0
    assert parse_last_event_id("7", 10) == 7
    assert parse_last_event_id(" 10 ", 10) == 10
    assert parse_last_event_id("99", 10) == 0  # from before a server restart → full snapshot
    assert parse_last_event_id("abc", 10) == 0
    assert parse_last_event_id("-3", 10) == 0


async def asgi_stream(app, headers=(), hold=0.05):
    """Drive the ASGI app directly, then disconnect; returns (start message, body)."""
    sent = []
    disconnect = asyncio.Event()
    first = True

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/stream/prices",
        "raw_path": b"/api/stream/prices",
        "query_string": b"",
        "root_path": "",
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
        "headers": [(k.encode(), v.encode()) for k, v in headers],
    }
    task = asyncio.create_task(app(scope, receive, send))
    await asyncio.sleep(hold)
    disconnect.set()
    await asyncio.wait_for(task, timeout=2)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body").decode()
    return start, body


async def test_endpoint_headers_snapshot_and_disconnect():
    cache = PriceCache()
    cache.update("005930", 75_000)
    cache.update("000660", 180_000)
    app = FastAPI()
    app.include_router(create_stream_router(cache, interval=0.01))
    start, body = await asgi_stream(app)
    assert start["status"] == 200
    headers = {k.decode(): v.decode() for k, v in start["headers"]}
    assert headers["content-type"].startswith("text/event-stream")
    assert headers["cache-control"] == "no-cache"
    assert headers["x-accel-buffering"] == "no"
    assert body.startswith("retry: 2000\n\n")
    events, _ = parse_frames([body.split("\n\n", 1)[1]])
    assert [json.loads(e["data"])["ticker"] for e in events] == ["005930", "000660"]


async def test_endpoint_honours_last_event_id_header():
    cache = PriceCache()
    cache.update("005930", 75_000)
    cache.update("000660", 180_000)
    app = FastAPI()
    app.include_router(create_stream_router(cache, interval=0.01))
    _, body = await asgi_stream(app, headers=[("last-event-id", "1")])
    events, _ = parse_frames([body.split("\n\n", 1)[1]])
    assert [json.loads(e["data"])["ticker"] for e in events] == ["000660"]


def test_router_factory_is_reentrant():
    cache = PriceCache()
    r1, r2 = create_stream_router(cache), create_stream_router(cache)
    assert r1 is not r2
    assert [r.path for r in r1.routes] == ["/api/stream/prices"]
    assert [r.path for r in r2.routes] == ["/api/stream/prices"]
