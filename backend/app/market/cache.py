"""Thread-safe in-memory price cache."""

from __future__ import annotations

import threading
from datetime import UTC, datetime

from .models import PriceQuote


class PriceCache:
    """Latest quote per ticker.

    Writers: exactly one MarketDataSource (simulator loop, or the yfinance poller
    which may write from a worker thread). Readers: SSE stream, REST endpoints,
    trade execution. Every write bumps a monotonically increasing ``version``;
    SSE clients use it to send only what changed.
    """

    def __init__(self) -> None:
        self._quotes: dict[str, PriceQuote] = {}
        self._version = 0
        self._lock = threading.Lock()

    def update(self, ticker: str, price: int, ts: datetime | None = None) -> PriceQuote:
        """Record a new price. ``price`` must be a positive int (KRW).

        The first sighting of a ticker sets ``session_open`` and ``prev_price``
        to the same value (direction ``flat``).
        """
        if isinstance(price, bool) or not isinstance(price, int):
            raise TypeError(f"price must be int KRW, got {type(price).__name__}")
        if price <= 0:
            raise ValueError(f"price must be positive, got {price}")
        ts = ts or datetime.now(UTC)
        with self._lock:
            old = self._quotes.get(ticker)
            self._version += 1
            quote = PriceQuote(
                ticker=ticker,
                price=price,
                prev_price=old.price if old else price,
                session_open=old.session_open if old else price,
                timestamp=ts,
                version=self._version,
            )
            self._quotes[ticker] = quote
            return quote

    def get(self, ticker: str) -> PriceQuote | None:
        with self._lock:
            return self._quotes.get(ticker)

    def price(self, ticker: str) -> int | None:
        quote = self.get(ticker)
        return quote.price if quote else None

    def get_all(self) -> dict[str, PriceQuote]:
        """Shallow copy of all current quotes."""
        with self._lock:
            return dict(self._quotes)

    def changed_since(self, version: int) -> list[PriceQuote]:
        """Quotes written after ``version``, oldest first."""
        with self._lock:
            quotes = [q for q in self._quotes.values() if q.version > version]
        quotes.sort(key=lambda q: q.version)
        return quotes

    def remove(self, ticker: str) -> None:
        with self._lock:
            self._quotes.pop(ticker, None)

    @property
    def version(self) -> int:
        with self._lock:
            return self._version

    def __len__(self) -> int:
        with self._lock:
            return len(self._quotes)

    def __contains__(self, ticker: object) -> bool:
        with self._lock:
            return ticker in self._quotes
