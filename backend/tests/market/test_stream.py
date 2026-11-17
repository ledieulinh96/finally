import asyncio
import json

from app.market.cache import PriceCache
from app.market.stream import create_stream_router, generate_events


def never():
    async def f():
        return False

    return f


def disconnect_after(n):
    calls = {"n": 0}

    async def f():
        calls["n"] += 1
        return calls["n"] > n

    return f


def parse(frames):
    out = []
    for fr in frames:
        if fr.startswith("id:"):
            lines = fr.strip().split("\n")
            out.append((int(lines[0][4:]), json.loads(lines[1][6:])))
    return out


async def collect(gen):
    return [f async for f in gen]


async def test_initial_snapshot_then_only_changes():
    c = PriceCache()
    c.update("005930", 75000)
    c.update("000660", 180000)
    frames = []

    async def run():
        async for f in generate_events(c, lambda t: f"N{t}", disconnect_after(3), interval=0.01):
            frames.append(f)
            if len(parse(frames)) == 2 and not hasattr(run, "done"):
                run.done = True
                c.update("005930", 75100)

    await run()
    assert frames[0] == "retry: 2000\n\n"
    events = parse(frames)
    assert [e["ticker"] for _, e in events[:2]] == ["005930", "000660"]
    assert events[0][1]["name"] == "N005930"
    assert [e["ticker"] for _, e in events[2:]] == ["005930"]
    assert events[2][1]["direction"] == "up"
    assert [v for v, _ in events] == sorted(v for v, _ in events)


async def test_since_resumes():
    c = PriceCache()
    c.update("A00000", 1000)
    q = c.update("B00000", 2000)
    frames = await collect(generate_events(c, str, disconnect_after(1), since=q.version - 1, interval=0.0))
    assert [e["ticker"] for _, e in parse(frames)] == ["B00000"]


async def test_keepalive_when_idle():
    frames = await collect(generate_events(PriceCache(), str, disconnect_after(5), interval=1, keepalive=2))
    assert ": keepalive\n\n" in frames


async def test_disconnect_ends_generator():
    frames = await asyncio.wait_for(collect(generate_events(PriceCache(), str, disconnect_after(0))), 1)
    assert frames == ["retry: 2000\n\n"]


def test_router_per_call_has_single_route():
    c = PriceCache()
    r1, r2 = create_stream_router(c), create_stream_router(c)
    assert r1 is not r2
    assert [r.path for r in r1.routes] == ["/api/stream/prices"]
    assert [r.path for r in r2.routes] == ["/api/stream/prices"]


async def test_endpoint_returns_sse_response_and_reads_last_event_id():
    from types import SimpleNamespace

    c = PriceCache()
    c.update("005930", 75000)
    q = c.update("000660", 180000)
    route = create_stream_router(c, lambda t: "N").routes[0]

    async def disc():
        return True

    req = SimpleNamespace(headers={"last-event-id": str(q.version - 1)}, is_disconnected=disc)
    resp = await route.endpoint(req)
    assert resp.media_type == "text/event-stream"
    assert resp.headers["cache-control"] == "no-cache"
    assert resp.headers["x-accel-buffering"] == "no"
