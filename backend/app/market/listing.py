"""Bundled KRX listing (ticker -> English name + market) and a name registry."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

DEFAULT_LISTING_PATH = Path(__file__).resolve().parents[2] / "schema" / "krx_listing.csv"


@dataclass(frozen=True)
class ListingEntry:
    ticker: str
    name: str
    market: str  # "KOSPI" | "KOSDAQ" | "KONEX"


def load_listing(path: Path | str = DEFAULT_LISTING_PATH) -> dict[str, ListingEntry]:
    """Load the listing CSV; a missing file yields an empty listing."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open(newline="", encoding="utf-8") as f:
        return {
            row["ticker"].strip(): ListingEntry(
                row["ticker"].strip(), row["name_en"].strip(), row["market"].strip().upper()
            )
            for row in csv.DictReader(f)
            if row.get("ticker")
        }


def yfinance_suffix(market: str) -> str:
    return ".KQ" if market.upper() == "KOSDAQ" else ".KS"


class NameRegistry:
    """ticker -> display name. Falls back to the listing, then to the ticker itself."""

    def __init__(self, listing: dict[str, ListingEntry] | None = None) -> None:
        self._listing = listing if listing is not None else load_listing()
        self._names: dict[str, str] = {}

    def set(self, ticker: str, name: str) -> None:
        self._names[ticker] = name

    def get(self, ticker: str) -> str:
        if ticker in self._names:
            return self._names[ticker]
        entry = self._listing.get(ticker)
        return entry.name if entry else ticker
