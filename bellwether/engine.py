"""Engine orchestration: scan -> classify -> select -> size -> render.

Ties the modules together for a single scan pass over a pool of tickers and,
optionally, applies the resulting signals to the paper portfolio (managing open
positions, stop/target exits, and the circuit breaker).
"""

from __future__ import annotations

from datetime import datetime, timezone

from . import data, dashboard, regime as regime_mod, risk, strategy
from .data import DataGap
from .portfolio import Portfolio, Position


def _manage_open_positions(pf: Portfolio, prices: dict[str, float]) -> list[str]:
    """Close positions whose stop or take-profit has been hit. Returns log lines."""
    logs: list[str] = []
    for ticker in list(pf.positions):
        pos = pf.positions[ticker]
        price = prices.get(ticker)
        if price is None:
            continue
        if pos.units > 0 and price <= pos.stop:
            pnl = pf.close_position(ticker, price)
            logs.append(f"[EXIT] {ticker} STOP hit @ ${price:,.2f} | realized ${pnl:,.2f}")
        elif pos.units > 0 and price >= pos.take_profit:
            pnl = pf.close_position(ticker, price)
            logs.append(f"[EXIT] {ticker} TARGET hit @ ${price:,.2f} | realized ${pnl:,.2f}")
    return logs


def scan(
    tickers: list[str],
    pf: Portfolio,
    period: str = "6mo",
    interval: str = "1d",
    apply_trades: bool = False,
    base_risk: float = risk.BASE_RISK_RATIO,
) -> str:
    """Run one full scan pass and return the rendered dashboard text."""
    out: list[str] = []
    prices: dict[str, float] = {}
    frames = {}

    # 1) Pull data first so we can mark the book before deciding anything.
    errors: dict[str, str] = {}
    for tk in tickers:
        try:
            df = data.fetch(tk, period=period, interval=interval)
            frames[tk] = df
            prices[tk] = data.latest_price(df)
        except DataGap as exc:
            errors[tk] = str(exc)

    # Mark open positions even if some feeds failed; roll the daily anchor.
    pf.roll_day_if_needed(prices)
    exit_logs = _manage_open_positions(pf, prices) if apply_trades else []

    daily_pnl = pf.daily_pnl_pct(prices)
    frozen = risk.circuit_breaker_tripped(daily_pnl)

    out.append(dashboard.header(pf.market_value(prices), daily_pnl, frozen))
    if frozen:
        out.append(dashboard.circuit_breaker_block(daily_pnl, risk.MAX_DAILY_LOSS))
    for line in exit_logs:
        out.append("\n" + line)

    # 2) Evaluate each verified asset.
    for tk in tickers:
        if tk in errors:
            out.append(dashboard.error_block(tk, errors[tk]))
            continue

        df = frames[tk]
        reg = regime_mod.classify(df)
        sig = strategy.generate(df, reg)
        sizing = risk.position_size(
            pf.cash, sig.entry, sig.stop, reg.atr_pct, base_risk=base_risk
        )

        # Circuit breaker freezes new BUYs; SELL/HOLD still allowed.
        effective = sig
        if frozen and sig.action == "BUY":
            effective = strategy.Signal(
                "HOLD", sig.framework, sig.conviction,
                "Signal suppressed: circuit breaker active (daily loss limit breached).",
                sig.entry, sig.stop, sig.take_profit, sig.atr,
            )
            sizing = risk.position_size(pf.cash, sig.entry, sig.entry, reg.atr_pct, base_risk)

        out.append(dashboard.asset_block(tk, prices[tk], reg, effective, sizing))

        if apply_trades and effective.action == "BUY" and sizing.units > 0 and tk not in pf.positions:
            pf.open_position(Position(
                ticker=tk, units=sizing.units, entry=effective.entry,
                stop=effective.stop, take_profit=effective.take_profit,
                opened=datetime.now(timezone.utc).isoformat(),
            ))
            out.append(f"  -> FILLED (paper): long {sizing.units} {tk} @ ${effective.entry:,.2f}")
        elif apply_trades and effective.action == "SELL" and tk in pf.positions:
            pnl = pf.close_position(tk, prices[tk])
            out.append(f"  -> CLOSED (paper): {tk} @ ${prices[tk]:,.2f} | realized ${pnl:,.2f}")

    out.append(dashboard.footer())
    return "\n".join(out)
