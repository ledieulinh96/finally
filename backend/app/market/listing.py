"""Bundled KRX listing snapshot: English names and KOSPI/KOSDAQ market per ticker.

The CSV at ``backend/schema/krx_listing.csv`` (columns ``ticker,name_en,market``)
lets the backend resolve the yfinance suffix (PLAN Q1) and a display name
without any network call. It is a hand-curated snapshot of large caps; tickers
not in it fall back to ``.KS`` → ``.KQ`` probing and the yfinance ``shortName``.
To extend it, append rows; ``FinanceDataReader.StockListing("KRX")`` gives the
authoritative ``Market`` column (its names are Korean, so English names are
added by hand or from OpenDART ``corp_name_eng``).
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

Market = Literal["KOSPI", "KOSDAQ"]

LISTING_PATH = Path(__file__).resolve().parents[2] / "schema" / "krx_listing.csv"

YF_SUFFIX: dict[str, str] = {"KOSPI": ".KS", "KOSDAQ": ".KQ"}


@dataclass(frozen=True, slots=True)
class ListingEntry:
    ticker: str
    name_en: str
    market: Market

    @property
    def yf_symbol(self) -> str:
        return self.ticker + YF_SUFFIX[self.market]


def load_listing(path: Path = LISTING_PATH) -> dict[str, ListingEntry]:
    """Parse the listing CSV. Rows with an unknown market are skipped."""
    entries: dict[str, ListingEntry] = {}
    try:
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                ticker = (row.get("ticker") or "").strip().upper()
                market = (row.get("market") or "").strip().upper()
                name = (row.get("name_en") or "").strip()
                if len(ticker) != 6 or market not in YF_SUFFIX or not name:
                    continue
                entries[ticker] = ListingEntry(ticker, name, market)  # type: ignore[arg-type]
    except FileNotFoundError:
        logger.warning("KRX listing not found at %s; names fall back to ticker codes", path)
    return entries


@lru_cache(maxsize=1)
def default_listing() -> dict[str, ListingEntry]:
    return load_listing()


def lookup(ticker: str) -> ListingEntry | None:
    return default_listing().get(ticker)
