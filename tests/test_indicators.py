import numpy as np
import pandas as pd

from bellwether import indicators as ind


def _series(values):
    return pd.Series(values, dtype="float64")


def test_sma_basic():
    s = _series([1, 2, 3, 4, 5])
    out = ind.sma(s, 3)
    assert np.isnan(out.iloc[1])
    assert out.iloc[2] == 2.0
    assert out.iloc[4] == 4.0


def test_atr_positive_and_bounded():
    n = 100
    high = _series(np.linspace(10, 20, n) + 0.5)
    low = _series(np.linspace(10, 20, n) - 0.5)
    close = _series(np.linspace(10, 20, n))
    out = ind.atr(high, low, close, period=14).dropna()
    assert (out > 0).all()
    # Range here is ~1.0 per bar, so ATR should sit near that.
    assert 0.5 < out.iloc[-1] < 2.0


def test_rsi_all_gains_is_100():
    s = _series(np.arange(1, 60, dtype="float64"))  # strictly rising
    out = ind.rsi(s, 14).dropna()
    assert out.iloc[-1] == 100.0


def test_rsi_bounds():
    rng = np.random.default_rng(0)
    s = _series(100 + np.cumsum(rng.normal(0, 1, 200)))
    out = ind.rsi(s, 14).dropna()
    assert out.between(0, 100).all()


def test_bollinger_percent_b_ordering():
    rng = np.random.default_rng(1)
    s = _series(100 + np.cumsum(rng.normal(0, 1, 200)))
    lower, mid, upper = ind.bollinger_bands(s, 20, 2.0)
    valid = ~upper.isna()
    assert (lower[valid] <= mid[valid]).all()
    assert (mid[valid] <= upper[valid]).all()
