"""Technical indicators computed on OHLCV pandas frames.

All functions take/return pandas Series and never mutate their inputs. They are
deliberately dependency-light (numpy + pandas) so they can be unit-tested
without any network or broker access.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple moving average."""
    return series.rolling(window=period, min_periods=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False, min_periods=period).mean()


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """True Range = max of the three classic range measures."""
    prev_close = close.shift(1)
    ranges = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    )
    return ranges.max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's smoothing)."""
    tr = true_range(high, low, close)
    return tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (Wilder)."""
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    out = 100 - (100 / (1 + rs))
    # When there are zero losses RSI is defined as 100.
    out = out.where(avg_loss != 0, 100.0)
    return out


def bollinger_bands(
    close: pd.Series, period: int = 20, num_std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Return (lower, middle, upper) Bollinger Bands."""
    middle = sma(close, period)
    std = close.rolling(window=period, min_periods=period).std(ddof=0)
    upper = middle + num_std * std
    lower = middle - num_std * std
    return lower, middle, upper


def bollinger_percent_b(close: pd.Series, period: int = 20, num_std: float = 2.0) -> pd.Series:
    """%B — position of price within the Bollinger envelope (0=lower, 1=upper)."""
    lower, _, upper = bollinger_bands(close, period, num_std)
    width = (upper - lower).replace(0.0, np.nan)
    return (close - lower) / width


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD line, signal line, histogram."""
    macd_line = ema(close, fast) - ema(close, slow)
    signal_line = macd_line.ewm(span=signal, adjust=False, min_periods=signal).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def stochastic(
    high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    """Stochastic oscillator %K and %D."""
    lowest = low.rolling(k_period, min_periods=k_period).min()
    highest = high.rolling(k_period, min_periods=k_period).max()
    rng = (highest - lowest).replace(0.0, np.nan)
    percent_k = 100 * (close - lowest) / rng
    percent_d = percent_k.rolling(d_period, min_periods=d_period).mean()
    return percent_k, percent_d


def donchian(high: pd.Series, low: pd.Series, period: int = 20) -> tuple[pd.Series, pd.Series]:
    """Donchian channel (lower, upper) — the classic Turtle breakout bands.

    Uses the *prior* `period` bars (shifted) so the current bar can be tested for
    a genuine breakout beyond the established range.
    """
    upper = high.rolling(period, min_periods=period).max().shift(1)
    lower = low.rolling(period, min_periods=period).min().shift(1)
    return lower, upper


def supertrend(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 10, multiplier: float = 3.0
) -> tuple[pd.Series, pd.Series]:
    """Supertrend line and direction (+1 uptrend, -1 downtrend).

    Faithful to the canonical implementation used across freqtrade strategies:
    ATR-banded trailing stop that flips with price. Returns (line, direction).
    """
    atr_ = atr(high, low, close, period)
    hl2 = (high + low) / 2
    upper = (hl2 + multiplier * atr_).to_numpy()
    lower = (hl2 - multiplier * atr_).to_numpy()
    close_arr = close.to_numpy()
    n = len(close_arr)

    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    direction = np.full(n, 1.0)

    for i in range(1, n):
        if np.isnan(upper[i]):
            continue
        prev_fu = final_upper[i - 1]
        prev_fl = final_lower[i - 1]
        final_upper[i] = upper[i] if (np.isnan(prev_fu) or upper[i] < prev_fu or close_arr[i - 1] > prev_fu) else prev_fu
        final_lower[i] = lower[i] if (np.isnan(prev_fl) or lower[i] > prev_fl or close_arr[i - 1] < prev_fl) else prev_fl

        prev_st = st[i - 1]
        if np.isnan(prev_st) or prev_st == prev_fu:
            st[i] = final_upper[i] if close_arr[i] <= final_upper[i] else final_lower[i]
        else:
            st[i] = final_lower[i] if close_arr[i] >= final_lower[i] else final_upper[i]
        direction[i] = 1.0 if close_arr[i] > st[i] else -1.0

    return pd.Series(st, index=close.index), pd.Series(direction, index=close.index)


def adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Average Directional Index — trend *strength* (not direction)."""
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(np.where((up_move > down_move) & (up_move > 0), up_move, 0.0), index=high.index)
    minus_dm = pd.Series(np.where((down_move > up_move) & (down_move > 0), down_move, 0.0), index=low.index)

    tr = true_range(high, low, close)
    atr_ = tr.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    plus_di = 100 * (plus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_)
    minus_di = 100 * (minus_dm.ewm(alpha=1 / period, adjust=False, min_periods=period).mean() / atr_)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0.0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
