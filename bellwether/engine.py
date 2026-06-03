"""Engine orchestration: scan -> classify -> ensemble -> size -> structured result.

`run_scan` returns a ScanResult (pure data); rendering lives in dashboard.py so
the same scan can drive a one-shot print or a live auto-refreshing dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import data, regime as regime_mod, risk, strategy
from .data import DataGap
from .portfolio import Portfolio, Position
from .regime import Regime
from .risk import SizingResult
from .strategy import Signal

_CRYPTO_SOURCES = {"coinex", "coinex-futures", "coinex-spot"}


@dataclass
class AssetReport:
    ticker: str
    ok: bool
    price: float = 0.0
    error: str | None = None
    regime: Regime | None = None
    signal: Signal | None = None
    sizing: SizingResult | None = None
    filled: str | None = None  # note about any paper fill/close
    change_pct: float = 0.0    # 24h change


@dataclass
class ScanResult:
    portfolio_value: float
    daily_pnl_pct: float
    frozen: bool
    reports: list[AssetReport]
    exit_logs: list[str] = field(default_factory=list)
    source: str = "yahoo"
    interval: str = "1d"
    unit_label: str = "SHARES"
    quotes: dict = field(default_factory=dict)  # symbol -> data.Quote (live)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"))


def _manage_open_positions(pf: Portfolio, prices: dict[str, float], fmt) -> list[str]:
    logs: list[str] = []
    for ticker in list(pf.positions):
        pos = pf.positions[ticker]
        price = prices.get(ticker)
        if price is None:
            continue
        if pos.units > 0 and price <= pos.stop:
            pnl = pf.close_position(ticker, price)
            logs.append(f"{ticker} STOP hit @ {fmt(price)} | realized ${pnl:,.2f}")
        elif pos.units > 0 and price >= pos.take_profit:
            pnl = pf.close_position(ticker, price)
            logs.append(f"{ticker} TARGET hit @ {fmt(price)} | realized ${pnl:,.2f}")
    return logs


def run_scan(
    tickers: list[str],
    pf: Portfolio,
    period: str = "6mo",
    interval: str = "1d",
    apply_trades: bool = False,
    base_risk: float = risk.BASE_RISK_RATIO,
    source: str = "yahoo",
    bars: int = 500,
) -> ScanResult:
    """Run one full scan pass and return a structured ScanResult."""
    from .dashboard import fmt_price  # local import avoids a cycle at module load

    is_crypto = source in _CRYPTO_SOURCES
    step = 0.0001 if is_crypto else 1.0
    unit_label = "CONTRACTS" if is_crypto else "SHARES"

    prices: dict[str, float] = {}
    frames = {}
    errors: dict[str, str] = {}
    for tk in tickers:
        try:
            df = data.fetch(tk, source=source, period=period, interval=interval, bars=bars)
            frames[tk] = df
            prices[tk] = data.latest_price(df)
        except DataGap as exc:
            errors[tk] = str(exc)

    quote_map = data.quotes(tickers, source=source)

    pf.roll_day_if_needed(prices)
    exit_logs = _manage_open_positions(pf, prices, fmt_price) if apply_trades else []

    daily_pnl = pf.daily_pnl_pct(prices)
    frozen = risk.circuit_breaker_tripped(daily_pnl)

    reports: list[AssetReport] = []
    for tk in tickers:
        if tk in errors:
            reports.append(AssetReport(tk, ok=False, error=errors[tk]))
            continue

        df = frames[tk]
        reg = regime_mod.classify(df)
        sig = strategy.generate(df, reg)
        sizing = risk.position_size(pf.cash, sig.entry, sig.stop, reg.atr_pct, base_risk, step=step)

        effective = sig
        if frozen and sig.action == "BUY":
            effective = Signal(
                "HOLD", sig.framework, sig.conviction,
                "Suppressed: circuit breaker active (daily loss limit breached).",
                sig.entry, sig.stop, sig.take_profit, sig.atr, sig.score, sig.votes,
            )
            sizing = risk.position_size(pf.cash, sig.entry, sig.entry, reg.atr_pct, base_risk, step=step)

        filled = None
        if apply_trades and effective.action == "BUY" and sizing.units > 0 and tk not in pf.positions:
            pf.open_position(Position(
                ticker=tk, units=sizing.units, entry=effective.entry,
                stop=effective.stop, take_profit=effective.take_profit,
                opened=datetime.now(timezone.utc).isoformat(),
            ))
            filled = f"FILLED long {sizing.units} {tk} @ {fmt_price(effective.entry)}"
        elif apply_trades and effective.action == "SELL" and tk in pf.positions:
            pnl = pf.close_position(tk, prices[tk])
            filled = f"CLOSED {tk} @ {fmt_price(prices[tk])} | realized ${pnl:,.2f}"

        q = quote_map.get(tk)
        reports.append(AssetReport(
            tk, ok=True, price=prices[tk], regime=reg,
            signal=effective, sizing=sizing, filled=filled,
            change_pct=q.change_pct if q else 0.0,
        ))

    return ScanResult(
        portfolio_value=pf.market_value(prices),
        daily_pnl_pct=daily_pnl,
        frozen=frozen,
        reports=reports,
        exit_logs=exit_logs,
        source=source,
        interval=interval,
        unit_label=unit_label,
        quotes=quote_map,
    )
