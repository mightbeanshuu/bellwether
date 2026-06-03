"""Bellwether command-line interface.

Examples:
    bellwether scan NVDA AAPL MSFT
    bellwether scan --apply --period 1y SPY QQQ
    bellwether status
    bellwether reset --capital 250000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, risk
from .engine import scan
from .portfolio import DEFAULT_STATE_PATH, Portfolio

DEFAULT_POOL = ["NVDA", "AAPL", "MSFT", "SPY", "TSLA"]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bellwether",
        description="Bellwether — regime-adaptive trading signal engine.",
    )
    p.add_argument("--version", action="version", version=f"Bellwether {__version__}")
    p.add_argument("--state", default=str(DEFAULT_STATE_PATH), help="portfolio state file path")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="scan a pool of tickers and emit signals")
    s.add_argument("tickers", nargs="*", default=DEFAULT_POOL, help="tickers to scan")
    s.add_argument("--period", default="6mo", help="history window (e.g. 3mo, 6mo, 1y)")
    s.add_argument("--interval", default="1d", help="bar interval (e.g. 1d, 1h)")
    s.add_argument("--apply", action="store_true", help="apply signals to the paper portfolio")
    s.add_argument("--risk", type=float, default=risk.BASE_RISK_RATIO, help="base per-trade risk ratio")

    st = sub.add_parser("status", help="show the paper portfolio")
    st.add_argument("--state", default=str(DEFAULT_STATE_PATH))

    r = sub.add_parser("reset", help="reset the paper portfolio")
    r.add_argument("--capital", type=float, default=100_000.0, help="starting capital")

    return p


def _cmd_status(state_path: Path) -> int:
    pf = Portfolio.load(state_path)
    print(f"Bellwether portfolio @ {state_path}")
    print(f"  starting capital : ${pf.starting_capital:,.2f}")
    print(f"  cash             : ${pf.cash:,.2f}")
    print(f"  realized P&L     : ${pf.realized_pnl:,.2f}")
    print(f"  open positions   : {len(pf.positions)}")
    for tk, pos in pf.positions.items():
        print(f"    - {tk}: {pos.units} @ ${pos.entry:,.2f} (stop ${pos.stop:,.2f}, tp ${pos.take_profit:,.2f})")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    state_path = Path(getattr(args, "state", DEFAULT_STATE_PATH))

    if args.command == "status":
        return _cmd_status(state_path)

    if args.command == "reset":
        pf = Portfolio(starting_capital=args.capital, cash=args.capital, day_start_equity=args.capital)
        pf.save(state_path)
        print(f"Portfolio reset to ${args.capital:,.2f} at {state_path}")
        return 0

    if args.command == "scan":
        pf = Portfolio.load(state_path)
        report = scan(
            args.tickers, pf,
            period=args.period, interval=args.interval,
            apply_trades=args.apply, base_risk=args.risk,
        )
        print(report)
        if args.apply:
            pf.save(state_path)
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
