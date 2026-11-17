from app.market.cache import PriceCache
from app.market.factory import create_source
from app.market.simulator import SimulatorSource
from app.market.yfinance_source import YFinanceSource


def test_default_is_simulator():
    assert isinstance(create_source(PriceCache(), {}), SimulatorSource)
    assert isinstance(create_source(PriceCache(), {"USE_YFINANCE": "false"}), SimulatorSource)


def test_use_yfinance_true_case_insensitive():
    assert isinstance(create_source(PriceCache(), {"USE_YFINANCE": " TRUE "}), YFinanceSource)


def test_sim_env_config():
    env = {"SIM_SEED": "5", "SIM_TIME_SCALE": "60", "SIM_UPDATE_INTERVAL": "0.25", "SIM_EVENT_RATE": "0"}
    s = create_source(PriceCache(), env)
    assert s._dt == 0.25 and s._scale == 60 and s._p_event == 0


def test_invalid_numbers_fall_back():
    s = create_source(PriceCache(), {"SIM_TIME_SCALE": "abc", "SIM_SEED": "x"})
    assert s._scale == 200.0


def test_same_seed_same_prices():
    import asyncio

    def run():
        c = PriceCache()
        s = create_source(c, {"SIM_SEED": "3"})
        asyncio.run(s.add_ticker("005930"))
        for _ in range(50):
            s.step()
        return c.price("005930")

    assert run() == run()
