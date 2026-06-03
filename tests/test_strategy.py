import numpy as np
import pandas as pd

from bellwether import regime as regime_mod
from bellwether import strategy


def _frame(closes):
    closes = np.asarray(closes, dtype="float64")
    high = closes * 1.004
    low = closes * 0.996
    vol = np.full(len(closes), 1000.0)
    return pd.DataFrame({"Open": closes, "High": high, "Low": low, "Close": closes, "Volume": vol})


def test_strong_uptrend_is_buy():
    closes = np.linspace(100, 200, 160) + np.sin(np.arange(160) / 5)
    df = _frame(closes)
    reg = regime_mod.classify(df)
    sig = strategy.generate(df, reg)
    assert reg.direction == "up"
    assert sig.action == "BUY"
    assert sig.score > 0
    assert sig.stop < sig.entry < sig.take_profit


def test_strong_downtrend_is_sell():
    closes = np.linspace(200, 100, 160) + np.sin(np.arange(160) / 5)
    df = _frame(closes)
    reg = regime_mod.classify(df)
    sig = strategy.generate(df, reg)
    assert sig.action == "SELL"
    assert sig.score < 0
    assert sig.stop > sig.entry > sig.take_profit


def test_signal_carries_full_vote_panel():
    df = _frame(np.linspace(100, 140, 120))
    sig = strategy.generate(df, regime_mod.classify(df))
    names = {v.name for v in sig.votes}
    assert names == {"Supertrend", "MACD", "EMA", "Donchian", "Bollinger", "Stochastic", "RSI"}
    assert abs(round(sum(v.weight for v in sig.votes), 6) - 1.0) < 1e-9  # weights normalize
    assert -1.0 <= sig.score <= 1.0
