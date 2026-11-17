"""Market data subsystem for FinAlly (KRX: KOSPI / KOSDAQ).

Public API:
    PriceQuote                - immutable latest-price snapshot (int KRW)
    PriceCache                - thread-safe in-memory price store (versioned)
    MarketDataSource          - abstract interface for price producers
    SimulatorSource           - default GBM/factor-model simulator
    MarketSettings            - env-driven configuration
    create_market_data_source - factory (USE_YFINANCE selects yfinance)
    create_stream_router      - FastAPI router for GET /api/stream/prices
    NameRegistry              - ticker -> English company name
    TickerTracker             - keeps tracked set == watchlist ∪ positions
"""

from .base import MarketDataSource
from .cache import PriceCache
from .factory import MarketSettings, create_market_data_source
from .market_hours import is_market_open, market_session
from .models import PriceQuote
from .names import NameRegistry
from .seed_data import DEFAULT_TICKERS, SEED_PARAMS
from .simulator import SimulatorSource
from .stream import create_stream_router
from .ticks import normalize_ticker, snap_to_tick, tick_size
from .tracker import TickerTracker

__all__ = [
    "DEFAULT_TICKERS",
    "SEED_PARAMS",
    "MarketDataSource",
    "MarketSettings",
    "NameRegistry",
    "PriceCache",
    "PriceQuote",
    "SimulatorSource",
    "TickerTracker",
    "create_market_data_source",
    "create_stream_router",
    "is_market_open",
    "market_session",
    "normalize_ticker",
    "snap_to_tick",
    "tick_size",
]
