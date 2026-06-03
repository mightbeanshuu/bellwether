# 🐏 Bellwether

> A *bellwether* is the lead animal whose movement signals where the flock heads
> next — the original leading indicator. **Bellwether** is a regime-adaptive,
> **ensemble** trading-signal engine for the terminal: it turns *real* market
> data (stocks **and** crypto) into actionable `BUY` / `SELL` / `HOLD` calls with
> a transparent, weighted vote behind every decision — rendered as a beautiful
> live dashboard.

```
🐏 BELLWETHER v0.2.0  ● ACTIVE   SOURCE: coinex/15m   EQUITY: $100,000.00   DAILY P&L: +0.00%
╭──────────┬─────────────┬──────────────────────┬──────────┬─────────────┬──────────────┬────────╮
│ Ticker   │       Price │ Regime               │  Signal  │    Score    │ Conv.        │   Size │
├──────────┼─────────────┼──────────────────────┼──────────┼─────────────┼──────────────┼────────┤
│ BTCUSDT  │  $65,910.00 │ Steady Down-Trend    │  ▼ SELL  │  ▱▱▱▰▰│▱▱▱▱▱  │ ██████░░ 62% │ 1.5172 │
│ ETHUSDT  │   $1,828.83 │ Aggressive Down-Trend│  ■ HOLD  │  ▱▱▱▱▰│▱▱▱▱▱  │ ███░░░░░ 33% │      0 │
╰──────────┴─────────────┴──────────────────────┴──────────┴─────────────┴──────────────┴────────╯
  BTCUSDT  $65,910.00  score -0.37
  Trend Ensemble (Supertrend×3 + MACD + EMA + Donchian)
   Supertrend  -1.00  3x Supertrend ALL down        ORDER  SELL
   Donchian    -0.34  Donchian mid-range (22%)       ENTRY  $65,910.00
   RSI         -0.34  RSI 40 (trend-confirm)          STOP  $66,574.83
   ...                                              TARGET  $64,912.76
```

## ⚡ One-command install & run

```bash
git clone https://github.com/mightbeanshuu/bellwether && cd bellwether
./install.sh           # creates a venv, installs everything, adds a `bellwether` launcher
bellwether             # instant live crypto scan 🚀
```

Then it's just:

```bash
bellwether                              # default: scan top crypto on CoinEx
bellwether live                         # auto-refreshing dashboard (Ctrl-C to quit)
bellwether scan --source coinex BTCUSDT ETHUSDT SOLUSDT
bellwether scan --source yahoo NVDA AAPL MSFT SPY     # stocks
bellwether scan --apply BTCUSDT         # apply signals to the paper portfolio
bellwether status                       # inspect the paper book
bellwether reset --capital 250000
```

## 🌍 Data sources (real prices, never fabricated)

| Source | What | Symbols |
|--------|------|---------|
| `coinex` *(default)* | CoinEx USDT-perpetual **futures** | `BTCUSDT`, `ETHUSDT`, … |
| `coinex-spot` | CoinEx spot | `BTCUSDT`, … |
| `yahoo` | Equities / ETFs (yfinance) | `NVDA`, `SPY`, … |

If a feed is empty, too short, stale, or has NaNs in the latest bar, Bellwether
raises a `DataGap`, marks the asset `DATA_GAP`, and **skips it** — it never
guesses a price. This is research/education tooling, **not financial advice**,
and it emits signals + a paper ledger only (no broker, no real orders).

## 🧠 The ensemble (what makes the calls "better")

Inspired by the patterns in the most-starred open-source bots — notably
[freqtrade](https://github.com/freqtrade/freqtrade)'s multi-**Supertrend**
confluence and the voting/stacked-confirmation approach catalogued in
[awesome-systematic-trading](https://github.com/wangzhe3224/awesome-systematic-trading)
and [best-of-algorithmic-trading](https://github.com/merovinh/best-of-algorithmic-trading) —
Bellwether doesn't trust a lone crossover. It runs a **panel of voters**, each
casting a signed vote in `[-1, +1]`, then blends them with **regime-aware
weights** into one net score:

| Voter | Idea | Heaviest in |
|-------|------|-------------|
| **Supertrend ×3** | 3 ATR settings must agree (freqtrade-style confluence) | trends |
| **MACD** | histogram sign + momentum | trends |
| **EMA-20/50** | convergence/spread | trends |
| **Donchian** | 20-bar breakout (Turtle) | breakouts |
| **Bollinger %B** | mean reversion at the bands | ranges |
| **Stochastic** | oversold/overbought reversion | ranges |
| **RSI** | trend-confirm in trends, fade extremes in ranges | both |

The **regime** (ADX → trend strength, ATR% → volatility, EMA → direction)
re-weights the panel, so the engine leans on Supertrend/MACD/EMA/Donchian when
trending and Bollinger/Stochastic/RSI when ranging. A trade only fires when the
net score clears a ±0.25 no-trade band; conviction scales with `|score|`.

## 🛡️ Risk & guardrails

**Volatility-adjusted position sizing:**

```
size = (capital × risk_ratio) / |entry − stop|
```

`risk_ratio` (base **1.5%**) scales **down** as ATR% rises above a 2% reference
and is floored at **0.5%** — smaller bets into violent tape. Sizing supports
fractional lots (e.g. BTC) and never exceeds account equity (no leverage).
Stops/targets are ATR multiples so they breathe with each asset.

**Circuit breaker:** if mark-to-market daily P&L breaches **−2%**, the engine
flags `CIRCUIT BREAKER TRIGGERED`, freezes all new BUYs for the session, and
allows only SELL/HOLD.

## 🧪 Tests

```bash
pip install pytest && pytest -q     # 15 offline tests (indicators, risk, strategy)
```

## 🗂️ Layout

```
bellwether/
  data.py        # pluggable real OHLCV (yahoo / coinex) + DataGap gating
  indicators.py  # SMA/EMA, ATR, RSI, MACD, Bollinger, Stochastic, Donchian, Supertrend, ADX
  regime.py      # market-regime classification
  strategy.py    # regime-gated ensemble voting engine
  risk.py        # volatility-adjusted sizing + circuit breaker
  portfolio.py   # JSON-persisted paper ledger
  dashboard.py   # rich terminal UI
  engine.py      # scan orchestration -> structured ScanResult
  cli.py         # argparse CLI (scan / live / status / reset)
install.sh       # one-command venv + launcher install
tests/           # offline unit tests
```

## License

MIT
