"""Bundled KRX listing and the name registry."""

from app.market.listing import load_listing, lookup
from app.market.names import NameRegistry
from app.market.seed_data import DEFAULT_TICKERS, SEED_PARAMS
from app.market.ticks import is_valid_ticker


def test_bundled_listing_is_well_formed():
    listing = load_listing()
    assert len(listing) >= 50
    for t, e in listing.items():
        assert is_valid_ticker(t) and e.ticker == t
        assert e.market in {"KOSPI", "KOSDAQ"} and e.name_en
    for t in DEFAULT_TICKERS:
        assert listing[t].market == "KOSPI"
        assert listing[t].name_en == SEED_PARAMS[t].name


def test_lookup_and_yf_symbol():
    assert lookup("005930").yf_symbol == "005930.KS"
    assert lookup("247540").yf_symbol == "247540.KQ"
    assert lookup("999999") is None


def test_load_listing_skips_bad_rows_and_missing_file(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text(
        "ticker,name_en,market\n005930,Samsung,KOSPI\n12345,Short,KOSPI\n111111,X,KONEX\n222222,,KOSDAQ\n"
    )
    assert list(load_listing(p)) == ["005930"]
    assert load_listing(tmp_path / "missing.csv") == {}


def test_name_registry():
    names = NameRegistry({"123456": "Custom Co"})
    assert names.get("005930") == "Samsung Electronics"
    assert names.get("051910") == "LG Chem"  # from listing
    assert names.get("123456") == "Custom Co"
    assert names.get("654321") == "654321"  # unknown → code
    assert not names.known("654321")
    names.set("654321", "  New Co ")
    names.set("654321", "")  # ignored
    names.set("654321", None)
    assert names.get("654321") == "New Co"
