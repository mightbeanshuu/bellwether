"""Risk allocation: volatility-adjusted sizing + the daily circuit breaker.

Position size follows the engine's core formula:

    size = (capital * risk_ratio) / |entry - stop|

The risk_ratio is scaled *down* as the asset's ATR% rises, so we automatically
bet smaller into volatile tape. A hard daily-loss circuit breaker freezes all
new BUYs once realized+unrealized losses breach the configured fraction.
"""

from __future__ import annotations

from dataclasses import dataclass

BASE_RISK_RATIO = 0.015      # 1.5% of capital risked per trade in calm/normal vol
MIN_RISK_RATIO = 0.005       # floor in extreme vol
MAX_DAILY_LOSS = 0.02        # 2% hard daily drawdown limit


@dataclass(frozen=True)
class SizingResult:
    risk_ratio: float
    risk_capital: float       # dollars put at risk
    units: float              # whole shares (step=1) or fractional (e.g. BTC)
    notional: float           # units * entry
    per_unit_risk: float      # |entry - stop|


def scaled_risk_ratio(atr_pct: float, base: float = BASE_RISK_RATIO) -> float:
    """Scale the per-trade risk ratio down as volatility rises.

    Reference volatility is 2% ATR%. Above that, risk is throttled inversely to
    volatility and clamped to MIN_RISK_RATIO. At/below reference, full base risk.
    """
    reference = 0.02
    if atr_pct <= reference:
        return base
    ratio = base * (reference / atr_pct)
    return max(MIN_RISK_RATIO, round(ratio, 4))


def _floor_to_step(value: float, step: float) -> float:
    """Floor `value` to the nearest multiple of `step` (the lot/contract size)."""
    if step <= 0:
        return value
    units = (value // step) * step
    # Re-round to step's decimal precision to avoid float fuzz (e.g. 0.30000000004).
    decimals = max(0, len(f"{step:.10f}".rstrip("0").split(".")[-1]))
    return round(units, decimals)


def position_size(
    capital: float,
    entry: float,
    stop: float,
    atr_pct: float,
    base_risk: float = BASE_RISK_RATIO,
    step: float = 1.0,
) -> SizingResult:
    """Compute a volatility-adjusted position size.

    `step` is the tradable lot size: 1.0 for whole shares, e.g. 0.0001 for BTC.
    Returns zero units when the stop is degenerate (entry == stop) rather than
    dividing by zero — a missing/equal stop is treated as "no valid risk frame."
    """
    risk_ratio = scaled_risk_ratio(atr_pct, base_risk)
    risk_capital = capital * risk_ratio
    per_unit_risk = abs(entry - stop)
    if per_unit_risk <= 0:
        return SizingResult(risk_ratio, risk_capital, 0.0, 0.0, 0.0)

    units = _floor_to_step(risk_capital / per_unit_risk, step)
    # Never let a single position's notional exceed the account (no leverage).
    if units * entry > capital:
        units = _floor_to_step(capital / entry, step)
    return SizingResult(
        risk_ratio=risk_ratio,
        risk_capital=round(risk_capital, 2),
        units=units,
        notional=round(units * entry, 2),
        per_unit_risk=round(per_unit_risk, 4),
    )


def circuit_breaker_tripped(daily_pnl_pct: float, limit: float = MAX_DAILY_LOSS) -> bool:
    """True when the day's loss has breached the hard drawdown limit."""
    return daily_pnl_pct <= -abs(limit)
