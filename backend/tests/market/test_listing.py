from app.market.listing import NameRegistry, load_listing, yfinance_suffix


def test_bundled_listing_has_default_tickers():
    listing = load_listing()
    assert len(listing) == 10
    assert listing["005930"].name == "Samsung Electronics" and listing["005930"].market == "KOSPI"


def test_missing_file_is_empty(tmp_path):
    assert load_listing(tmp_path / "nope.csv") == {}


def test_custom_csv(tmp_path):
    p = tmp_path / "l.csv"
    p.write_text("ticker,name_en,market\n247540,Ecopro BM,kosdaq\n")
    e = load_listing(p)["247540"]
    assert e.market == "KOSDAQ" and yfinance_suffix(e.market) == ".KQ"
    assert yfinance_suffix("KOSPI") == ".KS" and yfinance_suffix("KONEX") == ".KS"


def test_name_registry_precedence():
    r = NameRegistry()
    assert r.get("005930") == "Samsung Electronics"
    assert r.get("999999") == "999999"
    r.set("999999", "New Co")
    r.set("005930", "Override")
    assert r.get("999999") == "New Co" and r.get("005930") == "Override"
