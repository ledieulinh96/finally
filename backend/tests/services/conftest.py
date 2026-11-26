"""Fixtures: a fully wired app on a temp DB, seeded simulator, mock LLM."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.market import MarketSettings


@pytest.fixture
def app_settings(tmp_path, monkeypatch) -> Settings:
    db_path = tmp_path / "finally.db"
    monkeypatch.setenv("DB_PATH", str(db_path))
    monkeypatch.setenv("LLM_MOCK", "true")
    monkeypatch.delenv("OPENDART_API_KEY", raising=False)
    return Settings(
        db_path=db_path,
        static_dir=tmp_path / "no-static",
        llm_mock=True,
        openrouter_api_key="",
        opendart_api_key="",
    )


@pytest.fixture
def app(app_settings):
    return create_app(MarketSettings(sim_seed=42, sim_event_rate=0.0), app_settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c
