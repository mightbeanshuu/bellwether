"""Market-regime classification.

The engine adapts its strategy to the *regime* rather than forcing one rigid
playbook onto every tape. We classify along two axes:

  * trend strength  -> ADX
  * volatility      -> ATR as a percentage of price (ATR%)

and fold those into a small, explicit set of regimes the strategy layer keys on.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from . import indicators as ind

# ADX thresholds (Wilder's classic bands).
ADX_TRENDING = 25.0
ADX_STRONG = 40.0

# ATR-as-%-of-price thresholds for volatility classification.
VOL_ELEVATED = 0.025  # 2.5% daily true range
VOL_EXTREME = 0.05    # 5% daily true range


@dataclass(frozen=True)
class Regime:
    label: str           # human-readable regime name
    trend: str           # "trending" | "ranging"
    direction: str       # "up" | "down" | "flat"
    volatility: str      # "calm" | "normal" | "elevated" | "extreme"
    adx: float
    atr_pct: float       # ATR / price


def _volatility_bucket(atr_pct: float) -> str:
    if atr_pct >= VOL_EXTREME:
        return "extreme"
    if atr_pct >= VOL_ELEVATED:
        return "elevated"
    if atr_pct >= VOL_ELEVATED / 2:
        return "normal"
    return "calm"


def classify(df: pd.DataFrame) -> Regime:
    """Classify the most recent bar's regime from an OHLCV frame.

    Expects columns: High, Low, Close. Uses the last fully-formed row.
    """
    high, low, close = df["High"], df["Low"], df["Close"]

    adx_val = float(ind.adx(high, low, close).iloc[-1])
    atr_val = float(ind.atr(high, low, close).iloc[-1])
    price = float(close.iloc[-1])
    atr_pct = atr_val / price if price else 0.0

    fast = float(ind.ema(close, 20).iloc[-1])
    slow = float(ind.ema(close, 50).iloc[-1])
    if fast > slow * 1.001:
        direction = "up"
    elif fast < slow * 0.999:
        direction = "down"
    else:
        direction = "flat"

    trend = "trending" if adx_val >= ADX_TRENDING else "ranging"
    vol = _volatility_bucket(atr_pct)

    if trend == "trending":
        strength = "Aggressive" if adx_val >= ADX_STRONG else "Steady"
        label = f"{strength} {direction.title()}-Trend"
    else:
        label = "Range-Bound / Mean-Reverting"
    if vol in ("elevated", "extreme"):
        label = f"High-Velocity {label}"

    return Regime(
        label=label,
        trend=trend,
        direction=direction,
        volatility=vol,
        adx=adx_val,
        atr_pct=atr_pct,
    )
