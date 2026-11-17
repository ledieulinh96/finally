"""Test doubles shared by market data tests."""

from __future__ import annotations


class FakeFetcher:
    """In-memory QuoteFetcher. ``prices`` maps yfinance symbols to floats."""

    def __init__(self, prices=None, names=None):
        self.prices: dict[str, float] = dict(prices or {})
        self.names: dict[str, str] = dict(names or {})
        self.fail = False
        self.batch_calls: list[list[str]] = []
        self.probe_calls: list[str] = []

    def fetch_batch(self, symbols):
        self.batch_calls.append(list(symbols))
        if self.fail:
            raise ConnectionError("yahoo unreachable")
        return {s: self.prices[s] for s in symbols if s in self.prices}

    def probe(self, symbol):
        self.probe_calls.append(symbol)
        if self.fail:
            return None
        return self.prices.get(symbol)

    def short_name(self, symbol):
        return self.names.get(symbol)
