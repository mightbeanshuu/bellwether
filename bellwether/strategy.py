"""Strategy selection + signal generation.

The engine picks the framework that fits the active regime:

  * trending  -> Quantitative Momentum (EMA convergence + RSI confirmation)
  * ranging   -> Mean Reversion (Bollinger %B oscillator)

Each strategy emits a Signal carrying the action, a 0..1 conviction score, and
a plain-English rationale. Stops/targets are anchored to ATR so they scale with
the asset's own volatility rather than arbitrary fixed percentages.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import indicators as ind
from .regime import Regime


@dataclass(frozen=True)
class Signal:
    action: str            # "BUY" | "SELL" | "HOLD"
    framework: str         # name of the chosen algorithmic paradigm
    conviction: float      # 0..1
    rationale: str
    entry: float
    stop: float
    take_profit: float
    atr: float


def _momentum(df: pd.DataFrame, regime: Regime) -> Signal:
    close = df["Close"]
    high, low = df["High"], df["Low"]
    price = float(close.iloc[-1])
    atr_val = float(ind.atr(high, low, close).iloc[-1])

    ema_fast = ind.ema(close, 20)
    ema_slow = ind.ema(close, 50)
    rsi_val = float(ind.rsi(close).iloc[-1])

    fast_now, slow_now = float(ema_fast.iloc[-1]), float(ema_slow.iloc[-1])
    spread = (fast_now - slow_now) / slow_now if slow_now else 0.0

    framework = "Multi-Timeframe Quantitative Momentum (EMA-20/50 + RSI)"

    # Long bias: fast above slow, healthy but not blown-off RSI.
    if regime.direction == "up" and fast_now > slow_now and 50 <= rsi_val < 78:
        conviction = min(1.0, 0.4 + abs(spread) * 12 + (regime.adx - 25) / 100)
        stop = price - 2.0 * atr_val
        target = price + 3.0 * atr_val
        return Signal(
            "BUY", framework, round(conviction, 3),
            f"EMA-20 ({fast_now:.2f}) above EMA-50 ({slow_now:.2f}) by {spread*100:.2f}%; "
            f"ADX {regime.adx:.1f} confirms trend; RSI {rsi_val:.1f} has room to run.",
            price, round(stop, 2), round(target, 2), atr_val,
        )

    # Short/exit bias on a confirmed down-trend.
    if regime.direction == "down" and fast_now < slow_now and 22 < rsi_val <= 50:
        conviction = min(1.0, 0.4 + abs(spread) * 12 + (regime.adx - 25) / 100)
        stop = price + 2.0 * atr_val
        target = price - 3.0 * atr_val
        return Signal(
            "SELL", framework, round(conviction, 3),
            f"EMA-20 ({fast_now:.2f}) below EMA-50 ({slow_now:.2f}) by {abs(spread)*100:.2f}%; "
            f"ADX {regime.adx:.1f} confirms downtrend; RSI {rsi_val:.1f}.",
            price, round(stop, 2), round(target, 2), atr_val,
        )

    return Signal(
        "HOLD", framework, 0.0,
        f"Trend present (ADX {regime.adx:.1f}) but entry filters unmet "
        f"(RSI {rsi_val:.1f}, EMA spread {spread*100:.2f}%). Standing aside.",
        price, price, price, atr_val,
    )


def _mean_reversion(df: pd.DataFrame, regime: Regime) -> Signal:
    close = df["Close"]
    high, low = df["High"], df["Low"]
    price = float(close.iloc[-1])
    atr_val = float(ind.atr(high, low, close).iloc[-1])

    pct_b = float(ind.bollinger_percent_b(close).iloc[-1])
    _, mid, _ = ind.bollinger_bands(close)
    mid_now = float(mid.iloc[-1])
    rsi_val = float(ind.rsi(close).iloc[-1])

    framework = "Mean Reversion (Bollinger %B oscillator + RSI)"

    # Oversold snap-back: price near/below lower band.
    if pct_b <= 0.05 and rsi_val < 35:
        conviction = min(1.0, 0.45 + (0.05 - pct_b) * 6 + (35 - rsi_val) / 60)
        stop = price - 1.5 * atr_val
        target = mid_now  # revert to the mean
        return Signal(
            "BUY", framework, round(conviction, 3),
            f"%B {pct_b:.2f} (lower band) + RSI {rsi_val:.1f} oversold in a range; "
            f"reversion target = mid-band {mid_now:.2f}.",
            price, round(stop, 2), round(target, 2), atr_val,
        )

    # Overbought fade: price near/above upper band.
    if pct_b >= 0.95 and rsi_val > 65:
        conviction = min(1.0, 0.45 + (pct_b - 0.95) * 6 + (rsi_val - 65) / 60)
        stop = price + 1.5 * atr_val
        target = mid_now
        return Signal(
            "SELL", framework, round(conviction, 3),
            f"%B {pct_b:.2f} (upper band) + RSI {rsi_val:.1f} overbought in a range; "
            f"reversion target = mid-band {mid_now:.2f}.",
            price, round(stop, 2), round(target, 2), atr_val,
        )

    return Signal(
        "HOLD", framework, 0.0,
        f"Range-bound but price mid-channel (%B {pct_b:.2f}, RSI {rsi_val:.1f}); "
        f"no edge at the bands.",
        price, price, price, atr_val,
    )


def generate(df: pd.DataFrame, regime: Regime) -> Signal:
    """Route to the framework that matches the regime, then emit a Signal."""
    if regime.trend == "trending":
        return _momentum(df, regime)
    return _mean_reversion(df, regime)
