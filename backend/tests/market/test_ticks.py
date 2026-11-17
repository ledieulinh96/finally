"""KRX tick table, price limits and ticker validation."""

import pytest

from app.market.ticks import (
    is_valid_ticker,
    limit_band,
    normalize_ticker,
    snap_down,
    snap_to_tick,
    snap_up,
    tick_size,
)


@pytest.mark.parametrize(
    ("price", "tick"),
    [
        (1, 1),
        (1_999, 1),
        (2_000, 5),
        (4_999, 5),
        (5_000, 10),
        (19_999, 10),
        (20_000, 50),
        (49_999, 50),
        (50_000, 100),
        (199_999, 100),
        (200_000, 500),
        (499_999, 500),
        (500_000, 1_000),
        (2_000_000, 1_000),
    ],
)
def test_tick_size_bands(price, tick):
    assert tick_size(price) == tick


@pytest.mark.parametrize(
    ("raw", "snapped"),
    [
        (75_037.0, 75_000),
        (75_051.0, 75_100),
        (199_960.0, 200_000),
        (812_345.6, 812_000),
        (1_234.4, 1_234),
        (0.3, 1),
        (40_024.9, 40_000),
    ],
)
def test_snap_to_tick(raw, snapped):
    out = snap_to_tick(raw)
    assert out == snapped
    assert isinstance(out, int)
    assert out % tick_size(out) == 0


@pytest.mark.parametrize("bad", [0, -5, float("nan"), float("inf")])
def test_snap_rejects_invalid(bad):
    with pytest.raises(ValueError):
        snap_to_tick(bad)


def test_snap_down_and_up_are_tick_aligned():
    for p in [1_999.5, 49_990.0, 199_950.0, 499_700.0, 75_050.0]:
        d, u = snap_down(p), snap_up(p)
        assert d <= p <= u
        assert d % tick_size(d) == 0 and u % tick_size(u) == 0


def test_limit_band_never_exceeds_30_percent():
    for base in [75_000, 180_000, 800_000, 40_000, 1_555, 7_777]:
        lo, hi = limit_band(base)
        assert lo >= base * 0.7 and hi <= base * 1.3
        assert lo % tick_size(lo) == 0 and hi % tick_size(hi) == 0
    assert limit_band(75_000) == (52_500, 97_500)


@pytest.mark.parametrize(
    ("raw", "norm"),
    [
        ("005930", "005930"),
        (" 005930 ", "005930"),
        ("005930.KS", "005930"),
        ("247540.kq", "247540"),
        ("0088m0", "0088M0"),
    ],
)
def test_normalize_ticker(raw, norm):
    assert normalize_ticker(raw) == norm


@pytest.mark.parametrize("bad", ["5930", "AAPL", "0059300", "005-30", "", 5930])
def test_invalid_tickers(bad):
    assert not is_valid_ticker(bad)
    with pytest.raises(ValueError):
        normalize_ticker(bad)
