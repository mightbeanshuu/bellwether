"""Portfolio state — persisted to JSON so the engine has memory across runs.

Tracks cash, open positions, realized P&L, and the day's starting equity so the
circuit breaker can measure intraday drawdown. This is a *paper* ledger: it
records simulated fills, it does not touch a broker.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path

DEFAULT_STATE_PATH = Path.home() / ".bellwether" / "portfolio.json"


@dataclass
class Position:
    ticker: str
    units: int
    entry: float
    stop: float
    take_profit: float
    opened: str  # ISO timestamp


@dataclass
class Portfolio:
    starting_capital: float = 100_000.0
    cash: float = 100_000.0
    realized_pnl: float = 0.0
    positions: dict[str, Position] = field(default_factory=dict)
    day: str = field(default_factory=lambda: date.today().isoformat())
    day_start_equity: float = 100_000.0

    # ---- equity / P&L -------------------------------------------------
    def market_value(self, prices: dict[str, float]) -> float:
        """Mark-to-market equity = cash + open positions valued at `prices`."""
        mv = self.cash
        for tk, pos in self.positions.items():
            mv += pos.units * prices.get(tk, pos.entry)
        return mv

    def daily_pnl_pct(self, prices: dict[str, float]) -> float:
        if not self.day_start_equity:
            return 0.0
        return (self.market_value(prices) - self.day_start_equity) / self.day_start_equity

    def roll_day_if_needed(self, prices: dict[str, float]) -> None:
        """Reset the daily drawdown anchor when the calendar date changes."""
        today = date.today().isoformat()
        if today != self.day:
            self.day = today
            self.day_start_equity = self.market_value(prices)

    # ---- trade application -------------------------------------------
    def open_position(self, pos: Position) -> None:
        self.positions[pos.ticker] = pos
        self.cash -= pos.units * pos.entry

    def close_position(self, ticker: str, exit_price: float) -> float:
        pos = self.positions.pop(ticker)
        proceeds = pos.units * exit_price
        self.cash += proceeds
        pnl = (exit_price - pos.entry) * pos.units
        self.realized_pnl += pnl
        return pnl

    # ---- persistence --------------------------------------------------
    def to_dict(self) -> dict:
        d = asdict(self)
        d["positions"] = {k: asdict(v) for k, v in self.positions.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Portfolio":
        positions = {k: Position(**v) for k, v in d.get("positions", {}).items()}
        d = {**d, "positions": positions}
        # Tolerate older/newer schemas by keeping only known fields.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    @classmethod
    def load(cls, path: Path = DEFAULT_STATE_PATH, starting_capital: float = 100_000.0) -> "Portfolio":
        path = Path(path)
        if path.exists():
            return cls.from_dict(json.loads(path.read_text()))
        return cls(starting_capital=starting_capital, cash=starting_capital, day_start_equity=starting_capital)

    def save(self, path: Path = DEFAULT_STATE_PATH) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2))
