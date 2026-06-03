"""Terminal dashboard rendering — machine-readable, no conversational filler."""

from __future__ import annotations

from datetime import datetime, timezone

from . import __version__
from .regime import Regime
from .risk import SizingResult
from .strategy import Signal

RULE = "=" * 80
THIN = "-" * 80


def _ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def header(portfolio_value: float, daily_pnl_pct: float, frozen: bool) -> str:
    status = "FROZEN" if frozen else "ACTIVE"
    sign = "+" if daily_pnl_pct >= 0 else ""
    return (
        f"{RULE}\n"
        f"BELLWETHER_v{__version__} // {status} // "
        f"PORTFOLIO_VALUE: ${portfolio_value:,.2f} // "
        f"DAILY_P&L: {sign}{daily_pnl_pct*100:.2f}%\n"
        f"{RULE}"
    )


def asset_block(ticker: str, price: float, regime: Regime, signal: Signal, sizing: SizingResult) -> str:
    lines = [
        "",
        "[MARKET SCAN RECONNAISSANCE]",
        f"Target Ticker: {ticker}",
        f"Current Price: ${price:,.2f}",
        f"Market Regime: {regime.label} "
        f"(ADX {regime.adx:.1f}, ATR {regime.atr_pct*100:.2f}%, Vol: {regime.volatility})",
        "",
        "[ALGORITHM ENGINE SELECTION]",
        f"Selected Framework: {signal.framework}",
        f"Reasoning: {signal.rationale}",
        f"Conviction: {signal.conviction:.2f}",
        "",
        "[RISK MITIGATION SPECIFICATIONS]",
        f"Calculated Risk Ratio: {sizing.risk_ratio:.4f} ({sizing.risk_ratio*100:.2f}% portfolio risk)",
        f"Risk Capital: ${sizing.risk_capital:,.2f}",
        f"Calculated Stop-Loss: ${signal.stop:,.2f}",
        f"Calculated Take-Profit: ${signal.take_profit:,.2f}",
        f"Target Position Size: {sizing.units} units (notional ${sizing.notional:,.2f})",
        "",
        "[EXECUTION COMMAND]",
        THIN,
        f"ORDER_SIGNAL : {signal.action}",
        f"TICKER       : {ticker}",
        f"VOLUME       : {sizing.units} SHARES",
        f"ENTRY_LIMIT  : ${signal.entry:,.2f}",
        f"TIMESTAMP    : {_ts()}",
        THIN,
    ]
    return "\n".join(lines)


def error_block(ticker: str, message: str) -> str:
    return (
        "\n[MARKET SCAN RECONNAISSANCE]\n"
        f"Target Ticker: {ticker}\n"
        f"[ERROR: DATA_GAP] {message}\n"
        "ACTION: Asset skipped; advancing to next verified stream."
    )


def circuit_breaker_block(daily_pnl_pct: float, limit: float) -> str:
    return (
        f"\n{RULE}\n"
        f"[CRITICAL: CIRCUIT_BREAKER_TRIGGERED] "
        f"Daily P&L {daily_pnl_pct*100:.2f}% breached -{limit*100:.1f}% limit.\n"
        f"All BUY actions FROZEN for the session. SELL/HOLD only.\n"
        f"{RULE}"
    )


def footer() -> str:
    return "\nSTATUS: Scan complete. Awaiting next data vector stream..."
