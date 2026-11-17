"""Ticker → English company name registry.

Names are metadata, not price data, so they live here rather than in the
PriceQuote. The registry is seeded from the bundled listing and the default
universe; the API layer adds names from the watchlist table / OpenDART /
yfinance as tickers are added. Lookups never fail: an unknown ticker returns its
own code, so a position whose watchlist row was removed still has a name.
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from .listing import default_listing
from .seed_data import SEED_PARAMS


class NameRegistry:
    def __init__(self, initial: Mapping[str, str] | None = None) -> None:
        self._lock = threading.Lock()
        self._names: dict[str, str] = {}
        for ticker, entry in default_listing().items():
            self._names[ticker] = entry.name_en
        for ticker, params in SEED_PARAMS.items():
            self._names[ticker] = params.name
        if initial:
            self._names.update({t: n for t, n in initial.items() if n})

    def get(self, ticker: str) -> str:
        with self._lock:
            return self._names.get(ticker) or ticker

    def known(self, ticker: str) -> bool:
        with self._lock:
            return ticker in self._names

    def set(self, ticker: str, name: str | None) -> None:
        if not name or not name.strip():
            return
        with self._lock:
            self._names[ticker] = name.strip()
