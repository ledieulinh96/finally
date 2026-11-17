"""App wiring: lifespan starts the market source; health reports it."""

from fastapi.testclient import TestClient

from app.main import create_app
from app.market import DEFAULT_TICKERS, MarketSettings


def test_health_and_lifespan():
    app = create_app(MarketSettings(sim_seed=1))
    with TestClient(app) as client:
        r = client.get("/api/health")
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["market_data"] == "ok"
        assert body["source"] == "simulator"
        assert body["tickers"] == len(DEFAULT_TICKERS)
        assert body["market_session"] in {
            "pre_open",
            "regular",
            "closing_auction",
            "after_hours",
            "closed",
        }
        cache = app.state.price_cache
        assert all(cache.price(t) for t in DEFAULT_TICKERS)
    assert app.state.market_source.status == "stopped"


def test_stream_route_registered():
    app = create_app(MarketSettings(sim_seed=1))
    assert "/api/stream/prices" in {getattr(r, "path", None) for r in app.routes}
