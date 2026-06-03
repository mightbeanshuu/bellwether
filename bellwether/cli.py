"""Bellwether command-line interface.

Just run `bellwether` for an instant crypto signal scan. Other commands:

    bellwether scan NVDA AAPL MSFT            # stocks (yfinance)
    bellwether scan --source coinex BTCUSDT   # CoinEx futures
    bellwether live --source coinex           # auto-refreshing dashboard
    bellwether status                         # paper portfolio
    bellwether reset --capital 250000
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from . import __version__, risk
from .engine import run_scan
from .portfolio import DEFAULT_STATE_PATH, Portfolio

DEFAULT_POOL = ["NVDA", "AAPL", "MSFT", "SPY", "TSLA"]
CRYPTO_POOL = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
SOURCES = ["yahoo", "coinex", "coinex-futures", "coinex-spot"]


def _add_scan_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("tickers", nargs="*", help="symbols to scan (defaults depend on --source)")
    p.add_argument("--source", choices=SOURCES, default="coinex",
                   help="data source: coinex (crypto, default) or yahoo (stocks)")
    p.add_argument("--period", default="6mo", help="[yahoo] history window (e.g. 3mo, 6mo, 1y)")
    p.add_argument("--interval", default=None,
                   help="bar interval (1d, 4h, 1h, 15m, 5m...); default 1d stocks / 15m crypto")
    p.add_argument("--bars", type=int, default=500, help="[coinex] number of bars to pull (<=1000)")
    p.add_argument("--risk", type=float, default=risk.BASE_RISK_RATIO, help="base per-trade risk ratio")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bellwether",
        description="🐏 Bellwether — regime-adaptive ensemble trading signal engine.",
    )
    p.add_argument("--version", action="version", version=f"Bellwether {__version__}")
    p.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="portfolio state file path")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("scan", help="scan a pool of tickers and emit signals")
    _add_scan_args(s)
    s.add_argument("--apply", action="store_true", help="apply signals to the paper portfolio")

    lv = sub.add_parser("live", help="auto-refreshing live dashboard")
    _add_scan_args(lv)
    lv.add_argument("--every", type=int, default=30, help="refresh interval in seconds")
    lv.add_argument("--apply", action="store_true", help="apply signals each refresh")

    sub.add_parser("status", help="show the paper portfolio")

    r = sub.add_parser("reset", help="reset the paper portfolio")
    r.add_argument("--capital", type=float, default=100_000.0, help="starting capital")

    return p


def _resolve(args):
    is_crypto = args.source != "yahoo"
    tickers = args.tickers or (CRYPTO_POOL if is_crypto else DEFAULT_POOL)
    interval = args.interval or ("15m" if is_crypto else "1d")
    return tickers, interval


def _do_scan(args, state_path: Path):
    from .dashboard import render

    pf = Portfolio.load(state_path)
    tickers, interval = _resolve(args)
    result = run_scan(
        tickers, pf, period=args.period, interval=interval,
        apply_trades=args.apply, base_risk=args.risk, source=args.source, bars=args.bars,
    )
    render(result)
    if args.apply:
        pf.save(state_path)


def _do_live(args, state_path: Path):
    from rich.live import Live

    from .dashboard import build, console

    tickers, interval = _resolve(args)

    def _scan():
        pf = Portfolio.load(state_path)
        result = run_scan(
            tickers, pf, period=args.period, interval=interval,
            apply_trades=args.apply, base_risk=args.risk, source=args.source, bars=args.bars,
        )
        if args.apply:
            pf.save(state_path)
        return result

    console.print(f"[dim]Live dashboard — refreshing every {args.every}s. Ctrl-C to exit.[/dim]")
    try:
        if console.is_terminal:
            with Live(console=console, screen=True, auto_refresh=False) as live:
                while True:
                    live.update(build(_scan()), refresh=True)
                    time.sleep(max(5, args.every))
        else:  # piped / non-interactive: plain repeated render
            while True:
                console.print(build(_scan()))
                time.sleep(max(5, args.every))
    except KeyboardInterrupt:
        console.print("[dim]Live dashboard stopped.[/dim]")


def _do_status(state_path: Path):
    from rich.table import Table

    from .dashboard import console, fmt_price, fmt_units

    pf = Portfolio.load(state_path)
    console.print(f"[bold cyan]🐏 Bellwether paper portfolio[/bold cyan]  [dim]{state_path}[/dim]")
    console.print(f"  starting capital : [white]${pf.starting_capital:,.2f}[/white]")
    console.print(f"  cash             : [white]${pf.cash:,.2f}[/white]")
    pnl_style = "green" if pf.realized_pnl >= 0 else "red"
    console.print(f"  realized P&L     : [{pnl_style}]${pf.realized_pnl:,.2f}[/{pnl_style}]")
    if pf.positions:
        t = Table(title="open positions", title_style="bold")
        for col in ("Ticker", "Units", "Entry", "Stop", "Target"):
            t.add_column(col)
        for tk, pos in pf.positions.items():
            t.add_row(tk, fmt_units(pos.units), fmt_price(pos.entry),
                      fmt_price(pos.stop), fmt_price(pos.take_profit))
        console.print(t)
    else:
        console.print("  [dim]no open positions[/dim]")


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state_path = Path(getattr(args, "state", DEFAULT_STATE_PATH))

    # Bare `bellwether` => a default crypto scan.
    if args.command is None:
        args = _build_parser().parse_args(["scan"])
        args.state = str(state_path)

    if args.command == "status":
        _do_status(state_path)
    elif args.command == "reset":
        pf = Portfolio(starting_capital=args.capital, cash=args.capital, day_start_equity=args.capital)
        pf.save(state_path)
        from .dashboard import console
        console.print(f"[green]Portfolio reset to ${args.capital:,.2f}[/green] [dim]{state_path}[/dim]")
    elif args.command == "live":
        _do_live(args, state_path)
    elif args.command == "scan":
        _do_scan(args, state_path)
    else:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
