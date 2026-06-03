"""Regime-gated ENSEMBLE signal engine.

Rather than betting everything on one indicator, Bellwether runs a panel of
classic strategies — each casts a signed *vote* in [-1, +1] — then blends them
with regime-aware weights into a single net score. This mirrors how the most
popular open-source bots (e.g. freqtrade's multi-Supertrend confluence) stack
several confirmations instead of trusting a lone crossover.

Voters
------
  * Supertrend confluence (3 ATR settings must agree)   -> trend
  * MACD histogram / momentum                            -> trend
  * EMA-20/50 convergence                                -> trend
  * Donchian breakout (Turtle)                           -> breakout
  * Bollinger %B mean reversion                          -> range
  * Stochastic reversion                                 -> range
  * RSI (trend-confirm in trends, fade at extremes in ranges)

The regime decides each voter's weight, so the engine *adapts* its framework to
the tape: trends lean on Supertrend/MACD/EMA/Donchian; ranges lean on
Bollinger/Stochastic/RSI reversion.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from . import indicators as ind
from .regime import Regime

# Net-score thresholds for committing to a directional signal.
ENTER_THRESHOLD = 0.25


@dataclass(frozen=True)
class Vote:
    name: str
    value: float   # signed strength in [-1, +1] (+long / -short)
    weight: float  # regime-assigned importance
    note: str


@dataclass(frozen=True)
class Signal:
    action: str            # "BUY" | "SELL" | "HOLD"
    framework: str
    conviction: float      # 0..1
    rationale: str
    entry: float
    stop: float
    take_profit: float
    atr: float
    score: float = 0.0     # net signed ensemble score in [-1, +1]
    votes: list[Vote] = field(default_factory=list)


def _clamp(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------
# Individual voters — each returns a (signed value, note) pair.
# --------------------------------------------------------------------------
def _supertrend_vote(df) -> tuple[float, str]:
    high, low, close = df["High"], df["Low"], df["Close"]
    dirs = []
    for period, mult in ((10, 1.0), (11, 2.0), (12, 3.0)):
        _, d = ind.supertrend(high, low, close, period, mult)
        dirs.append(float(d.iloc[-1]))
    agree = sum(dirs)
    val = agree / 3.0  # +1 if all three up, -1 if all three down
    state = "ALL up" if agree == 3 else "ALL down" if agree == -3 else f"mixed ({agree:+.0f})"
    return val, f"3x Supertrend {state}"


def _macd_vote(df) -> tuple[float, str]:
    line, sig, hist = ind.macd(df["Close"])
    h, h_prev = float(hist.iloc[-1]), float(hist.iloc[-2])
    price = float(df["Close"].iloc[-1])
    norm = _clamp(h / (price * 0.01))  # scale histogram by ~1% of price
    rising = h > h_prev
    val = norm * (1.0 if rising else 0.6)
    return _clamp(val), f"MACD hist {h:+.2f} ({'rising' if rising else 'falling'})"


def _ema_vote(df) -> tuple[float, str]:
    close = df["Close"]
    fast = float(ind.ema(close, 20).iloc[-1])
    slow = float(ind.ema(close, 50).iloc[-1])
    spread = (fast - slow) / slow if slow else 0.0
    return _clamp(spread * 15), f"EMA20/50 spread {spread*100:+.2f}%"


def _donchian_vote(df) -> tuple[float, str]:
    high, low, close = df["High"], df["Low"], df["Close"]
    lower, upper = ind.donchian(high, low, 20)
    price = float(close.iloc[-1])
    up, lo = float(upper.iloc[-1]), float(lower.iloc[-1])
    if price >= up:
        return 1.0, f"Donchian breakout > 20-bar high {up:.2f}"
    if price <= lo:
        return -1.0, f"Donchian breakdown < 20-bar low {lo:.2f}"
    pos = (price - lo) / (up - lo) if up > lo else 0.5
    return _clamp((pos - 0.5) * 1.2), f"Donchian mid-range ({pos*100:.0f}%)"


def _bollinger_vote(df) -> tuple[float, str]:
    pct_b = float(ind.bollinger_percent_b(df["Close"]).iloc[-1])
    # Mean reversion: oversold (low %B) -> buy (+), overbought -> sell (-).
    val = _clamp((0.5 - pct_b) * 2.5)
    return val, f"Bollinger %B {pct_b:.2f}"


def _stochastic_vote(df) -> tuple[float, str]:
    k, d = ind.stochastic(df["High"], df["Low"], df["Close"])
    kv = float(k.iloc[-1])
    if kv <= 20:
        return _clamp((20 - kv) / 20 + 0.3), f"Stochastic %K {kv:.0f} oversold"
    if kv >= 80:
        return _clamp(-((kv - 80) / 20 + 0.3)), f"Stochastic %K {kv:.0f} overbought"
    return _clamp((50 - kv) / 100), f"Stochastic %K {kv:.0f}"


def _rsi_vote(df, regime: Regime) -> tuple[float, str]:
    rsi_val = float(ind.rsi(df["Close"]).iloc[-1])
    if regime.trend == "trending":
        # Trend-confirm: above 50 supports longs, below supports shorts.
        return _clamp((rsi_val - 50) / 30), f"RSI {rsi_val:.0f} (trend-confirm)"
    # Range: fade extremes.
    if rsi_val <= 35:
        return _clamp((35 - rsi_val) / 25 + 0.2), f"RSI {rsi_val:.0f} oversold"
    if rsi_val >= 65:
        return _clamp(-((rsi_val - 65) / 25 + 0.2)), f"RSI {rsi_val:.0f} overbought"
    return _clamp((50 - rsi_val) / 50), f"RSI {rsi_val:.0f}"


# --------------------------------------------------------------------------
# Regime-aware weighting
# --------------------------------------------------------------------------
def _weights(regime: Regime) -> dict[str, float]:
    if regime.trend == "trending":
        return {
            "Supertrend": 0.28, "MACD": 0.20, "EMA": 0.18, "Donchian": 0.18,
            "RSI": 0.10, "Bollinger": 0.03, "Stochastic": 0.03,
        }
    return {
        "Bollinger": 0.30, "Stochastic": 0.24, "RSI": 0.22, "Donchian": 0.10,
        "Supertrend": 0.08, "MACD": 0.03, "EMA": 0.03,
    }


def generate(df: pd.DataFrame, regime: Regime) -> Signal:
    """Run every voter, blend by regime weights, and emit a directional Signal."""
    price = float(df["Close"].iloc[-1])
    atr_val = float(ind.atr(df["High"], df["Low"], df["Close"]).iloc[-1])
    weights = _weights(regime)

    raw = {
        "Supertrend": _supertrend_vote(df),
        "MACD": _macd_vote(df),
        "EMA": _ema_vote(df),
        "Donchian": _donchian_vote(df),
        "Bollinger": _bollinger_vote(df),
        "Stochastic": _stochastic_vote(df),
        "RSI": _rsi_vote(df, regime),
    }

    votes = [Vote(name, val, weights[name], note) for name, (val, note) in raw.items()]
    score = sum(v.value * v.weight for v in votes)  # weights sum to 1.0
    framework = (
        "Trend Ensemble (Supertrend×3 + MACD + EMA + Donchian)"
        if regime.trend == "trending"
        else "Mean-Reversion Ensemble (Bollinger + Stochastic + RSI)"
    )

    # Tighter stops in ranges, wider trailing room in trends.
    stop_mult, tp_mult = (2.0, 3.0) if regime.trend == "trending" else (1.5, 2.0)
    conviction = round(_clamp(abs(score) / 0.6, 0, 1), 3)

    top = sorted(votes, key=lambda v: abs(v.value) * v.weight, reverse=True)[:3]
    drivers = "; ".join(v.note for v in top)

    if score >= ENTER_THRESHOLD:
        return Signal(
            "BUY", framework, conviction,
            f"Net ensemble score {score:+.2f}. Drivers: {drivers}.",
            price, round(price - stop_mult * atr_val, 4), round(price + tp_mult * atr_val, 4),
            atr_val, round(score, 3), votes,
        )
    if score <= -ENTER_THRESHOLD:
        return Signal(
            "SELL", framework, conviction,
            f"Net ensemble score {score:+.2f}. Drivers: {drivers}.",
            price, round(price + stop_mult * atr_val, 4), round(price - tp_mult * atr_val, 4),
            atr_val, round(score, 3), votes,
        )
    return Signal(
        "HOLD", framework, conviction,
        f"Net ensemble score {score:+.2f} inside ±{ENTER_THRESHOLD} no-trade band. "
        f"Mixed read: {drivers}.",
        price, price, price, atr_val, round(score, 3), votes,
    )
