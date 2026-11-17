"""Settings parsing and source selection."""

import pytest

from app.market.cache import PriceCache
from app.market.factory import MarketSettings, create_market_data_source
from app.market.simulator import SimulatorSource
from app.market.yfinance_source import YFinanceSource


def test_defaults():
    s = MarketSettings.from_env({})
    assert s == MarketSettings()
    assert (s.use_yfinance, s.sim_time_scale, s.sim_update_interval, s.sim_event_rate) == (
        False,
        200.0,
        0.5,
        0.1,
    )
    assert s.sim_seed is None


@pytest.mark.parametrize("val", ["true", "TRUE", " 1 ", "yes", "on"])
def test_use_yfinance_truthy(val):
    assert MarketSettings.from_env({"USE_YFINANCE": val}).use_yfinance


@pytest.mark.parametrize("val", ["false", "0", "", "nope"])
def test_use_yfinance_falsy(val):
    assert not MarketSettings.from_env({"USE_YFINANCE": val}).use_yfinance


def test_sim_overrides_and_invalid_values():
    env = {
        "SIM_SEED": "42",
        "SIM_TIME_SCALE": "60",
        "SIM_EVENT_RATE": "0",
        "SIM_UPDATE_INTERVAL": "0.25",
    }
    s = MarketSettings.from_env(env)
    assert (s.sim_seed, s.sim_time_scale, s.sim_event_rate, s.sim_update_interval) == (
        42,
        60.0,
        0.0,
        0.25,
    )
    bad = MarketSettings.from_env(
        {
            "SIM_SEED": "x",
            "SIM_TIME_SCALE": "-1",
            "SIM_EVENT_RATE": "-2",
            "SIM_UPDATE_INTERVAL": "abc",
            "YFINANCE_POLL_INTERVAL": "0",
        }
    )
    assert bad.sim_seed is None
    assert (bad.sim_time_scale, bad.sim_event_rate, bad.sim_update_interval) == (200.0, 0.1, 0.5)
    assert bad.yfinance_poll_interval == 15.0


def test_factory_selects_simulator_by_default():
    src = create_market_data_source(PriceCache(), MarketSettings())
    assert isinstance(src, SimulatorSource) and src.name == "simulator"


def test_factory_selects_yfinance():
    src = create_market_data_source(PriceCache(), MarketSettings(use_yfinance=True))
    assert isinstance(src, YFinanceSource) and src.name == "yfinance"


def test_factory_reads_os_environ(monkeypatch):
    monkeypatch.setenv("USE_YFINANCE", "true")
    assert isinstance(create_market_data_source(PriceCache()), YFinanceSource)
    monkeypatch.setenv("USE_YFINANCE", "false")
    assert isinstance(create_market_data_source(PriceCache()), SimulatorSource)
