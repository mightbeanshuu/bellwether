"""Beautiful terminal rendering powered by `rich`.

Renders a ScanResult as a polished dashboard: a header banner with portfolio
health, a per-asset signal table, and an expandable detail panel per actionable
asset (regime, ensemble vote breakdown, and the risk-managed execution command).
"""

from __future__ import annotations

from rich.align import Align
from rich.box import HEAVY, ROUNDED, SIMPLE
from rich.columns import Columns
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__

console = Console()

ACTION_STYLE = {"BUY": "bold green", "SELL": "bold red", "HOLD": "bold yellow"}
ACTION_ICON = {"BUY": "▲ BUY ", "SELL": "▼ SELL", "HOLD": "■ HOLD"}


# --------------------------------------------------------------------------
# Formatting helpers (reused by engine logs too)
# --------------------------------------------------------------------------
def fmt_price(p: float) -> str:
    if p == 0:
        return "$0.00"
    if abs(p) >= 1:
        return f"${p:,.2f}"
    if abs(p) >= 0.01:
        return f"${p:,.4f}"
    return f"${p:,.6f}"


def fmt_units(u: float) -> str:
    if u == int(u):
        return f"{int(u):,}"
    return f"{u:,.6f}".rstrip("0").rstrip(".")


def _conviction_bar(conviction: float, width: int = 10) -> str:
    filled = round(conviction * width)
    return "█" * filled + "░" * (width - filled)


def _score_bar(score: float, width: int = 11) -> Text:
    """A centered -1..+1 gauge: red left (short), green right (long)."""
    half = width // 2
    pos = int(round(_clamp(score) * half))
    cells = []
    for i in range(-half, half + 1):
        if i == 0:
            cells.append(("│", "dim"))
        elif 0 < i <= pos:
            cells.append(("▰", "green"))
        elif pos <= i < 0:
            cells.append(("▰", "red"))
        else:
            cells.append(("▱", "dim"))
    t = Text()
    for ch, style in cells:
        t.append(ch, style=style)
    return t


def _clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


# --------------------------------------------------------------------------
# Header
# --------------------------------------------------------------------------
def _pct(p: float) -> str:
    return f"{'+' if p >= 0 else ''}{p*100:.2f}%"


def ticker_strip(quotes: dict, prev_prices: dict | None = None) -> Panel:
    """A live price ribbon. Each cell flashes green/red on a tick vs prev_prices;
    when no prev is given (one-shot scan) it colors by the 24h change sign."""
    prev_prices = prev_prices or {}
    cells = []
    for sym, q in quotes.items():
        prev = prev_prices.get(sym)
        if prev is not None and q.last != prev:
            price_style = "bold green" if q.last > prev else "bold red"
            arrow = "▲" if q.last > prev else "▼"
        else:
            price_style = "bold green" if q.change_pct >= 0 else "bold red"
            arrow = "▲" if q.change_pct >= 0 else "▼"
        chg_style = "green" if q.change_pct >= 0 else "red"

        cell = Text(justify="center")
        cell.append(f"{sym}\n", style="bold white")
        cell.append(f"{arrow} {fmt_price(q.last)}\n", style=price_style)
        cell.append(_pct(q.change_pct), style=chg_style)
        cells.append(cell)

    if not cells:
        cells = [Text("waiting for live quotes…", style="dim italic")]
    return Panel(Columns(cells, equal=True, expand=True), title="● LIVE", title_align="left",
                 box=ROUNDED, border_style="green", padding=(0, 1))


def header_panel(result) -> Panel:
    pnl = result.daily_pnl_pct
    pnl_style = "green" if pnl >= 0 else "red"
    sign = "+" if pnl >= 0 else ""
    status = Text("● FROZEN", style="bold red") if result.frozen else Text("● ACTIVE", style="bold green")

    line = Text()
    line.append("🐏 BELLWETHER ", style="bold cyan")
    line.append(f"v{__version__}  ", style="dim")
    line.append_text(status)
    line.append(f"   SOURCE: {result.source}/{result.interval}   ", style="dim")
    line.append("EQUITY: ", style="dim")
    line.append(f"${result.portfolio_value:,.2f}", style="bold white")
    line.append("   DAILY P&L: ", style="dim")
    line.append(f"{sign}{pnl*100:.2f}%", style=f"bold {pnl_style}")

    sub = Text(result.timestamp, style="dim italic")
    return Panel(Group(Align.center(line), Align.center(sub)), box=HEAVY, border_style="cyan", padding=(0, 1))


# --------------------------------------------------------------------------
# Summary table
# --------------------------------------------------------------------------
def summary_table(result) -> Table:
    t = Table(box=ROUNDED, expand=True, border_style="grey37", header_style="bold white on grey23")
    t.add_column("Ticker", style="bold", no_wrap=True)
    t.add_column("Price", justify="right")
    t.add_column("24h", justify="right")
    t.add_column("Regime")
    t.add_column("Signal", justify="center")
    t.add_column("Score", justify="center")
    t.add_column("Conv.", justify="left")
    t.add_column("Size", justify="right")

    for r in result.reports:
        if not r.ok:
            t.add_row(r.ticker, "—", "—", Text("DATA_GAP", style="bold red"),
                      Text("SKIP", style="dim"), "—", "—", "—")
            continue
        sig = r.signal
        act_style = ACTION_STYLE[sig.action]
        regime_txt = Text(r.regime.label, style="white")
        regime_txt.append(f"\nADX {r.regime.adx:.0f} · ATR {r.regime.atr_pct*100:.2f}%", style="dim")
        conv = f"{_conviction_bar(sig.conviction)} {sig.conviction*100:.0f}%"
        chg_style = "green" if r.change_pct >= 0 else "red"
        t.add_row(
            r.ticker,
            fmt_price(r.price),
            Text(_pct(r.change_pct), style=chg_style),
            regime_txt,
            Text(ACTION_ICON[sig.action], style=act_style),
            _score_bar(sig.score),
            Text(conv, style=act_style),
            f"{fmt_units(r.sizing.units)}",
        )
    return t


# --------------------------------------------------------------------------
# Per-asset detail panels (only for actionable BUY/SELL)
# --------------------------------------------------------------------------
def _votes_table(sig) -> Table:
    vt = Table(box=SIMPLE, show_header=True, header_style="dim", expand=True, padding=(0, 1))
    vt.add_column("Voter", style="cyan", no_wrap=True)
    vt.add_column("Vote", justify="center")
    vt.add_column("Wt", justify="right", style="dim")
    vt.add_column("Read", style="white")
    for v in sorted(sig.votes, key=lambda x: abs(x.value) * x.weight, reverse=True):
        style = "green" if v.value > 0.05 else "red" if v.value < -0.05 else "dim"
        vt.add_row(v.name, Text(f"{v.value:+.2f}", style=style), f"{v.weight:.2f}", v.note)
    return vt


def detail_panel(r, unit_label: str) -> Panel:
    sig, sz = r.signal, r.sizing
    act_style = ACTION_STYLE[sig.action]

    cmd = Table.grid(padding=(0, 2))
    cmd.add_column(style="dim", justify="right")
    cmd.add_column(style="bold white")
    cmd.add_row("ORDER", Text(sig.action, style=act_style))
    cmd.add_row("ENTRY", fmt_price(sig.entry))
    cmd.add_row("STOP", Text(fmt_price(sig.stop), style="red"))
    cmd.add_row("TARGET", Text(fmt_price(sig.take_profit), style="green"))
    cmd.add_row("SIZE", f"{fmt_units(sz.units)} {unit_label}")
    cmd.add_row("RISK", f"{sz.risk_ratio*100:.2f}%  (${sz.risk_capital:,.0f})")
    cmd.add_row("NOTIONAL", f"${sz.notional:,.2f}")

    body = Group(
        Text(sig.framework, style="italic cyan"),
        Text(sig.rationale, style="white"),
        Text(""),
        Columns([_votes_table(sig), Panel(cmd, title="execution", box=ROUNDED,
                                          border_style=act_style.split()[-1], padding=(0, 1))],
                expand=True),
    )
    if r.filled:
        body = Group(body, Text(f"→ {r.filled}", style="bold magenta"))

    title = Text()
    title.append(f" {r.ticker} ", style=f"{act_style} reverse")
    title.append(f"  {fmt_price(r.price)}  ", style="bold white")
    title.append(f"score {sig.score:+.2f}", style="dim")
    return Panel(body, title=title, box=ROUNDED, border_style=act_style.split()[-1], padding=(1, 1))


# --------------------------------------------------------------------------
# Top-level render
# --------------------------------------------------------------------------
def build(result, prev_prices: dict | None = None) -> Group:
    parts = [header_panel(result)]
    if result.quotes:
        parts.append(ticker_strip(result.quotes, prev_prices))
    if result.frozen:
        parts.append(Panel(
            Text("CIRCUIT BREAKER TRIGGERED — daily loss limit breached. "
                 "All new BUYs frozen for the session (SELL/HOLD only).",
                 style="bold red", justify="center"),
            box=HEAVY, border_style="red"))
    for log in result.exit_logs:
        parts.append(Text(f"  ⚑ EXIT  {log}", style="bold magenta"))

    parts.append(summary_table(result))

    actionable = [r for r in result.reports if r.ok and r.signal.action in ("BUY", "SELL")]
    for r in actionable:
        parts.append(detail_panel(r, result.unit_label))

    if not actionable:
        parts.append(Align.center(Text("No actionable signals this pass — standing aside.", style="dim italic")))

    return Group(*parts)


def render(result, target_console: Console | None = None) -> None:
    (target_console or console).print(build(result))
