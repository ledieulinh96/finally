"""App wiring: lifespan starts the market source from the DB; health reports it."""

from app.market import DEFAULT_TICKERS


def test_health_and_lifespan(app, client):
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


def test_source_stopped_after_shutdown(app):
    from fastapi.testclient import TestClient

    with TestClient(app):
        assert app.state.market_source.status == "ok"
    assert app.state.market_source.status == "stopped"


def test_stream_route_registered(app):
    assert "/api/stream/prices" in {getattr(r, "path", None) for r in app.routes}


def test_held_ticker_tracked_on_startup(app_settings):
    """Positions not on the watchlist are tracked at startup (watchlist ∪ positions)."""
    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.market import MarketSettings

    app1 = create_app(MarketSettings(sim_seed=1), app_settings)
    with TestClient(app1) as c:
        assert (
            c.post(
                "/api/portfolio/trade", json={"ticker": "035720", "quantity": 1, "side": "buy"}
            ).status_code
            == 200
        )
        assert c.delete("/api/watchlist/035720").status_code == 200
    app2 = create_app(MarketSettings(sim_seed=1), app_settings)
    with TestClient(app2) as c:
        assert "035720" in app2.state.market_source.tickers
        assert c.get("/api/health").json()["tickers"] == len(DEFAULT_TICKERS)


def test_static_spa_fallback(tmp_path, app_settings):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app
    from app.market import MarketSettings

    static = tmp_path / "static"
    (static / "_next").mkdir(parents=True)
    (static / "index.html").write_text("<html>INDEX</html>")
    (static / "_next" / "app.js").write_text("console.log(1)")
    app = create_app(MarketSettings(sim_seed=1), replace(app_settings, static_dir=static))
    with TestClient(app) as c:
        assert "INDEX" in c.get("/").text
        assert "console.log" in c.get("/_next/app.js").text
        assert "INDEX" in c.get("/some/client/route").text
        assert c.get("/api/nope").status_code == 404
        assert c.get("/api/health").json()["status"] == "ok"
        assert c.get("/../../etc/passwd").status_code in (200, 404)
