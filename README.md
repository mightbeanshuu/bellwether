# 🐏 Bellwether

> A *bellwether* is the lead animal whose movement signals where the flock heads
> next — the original leading indicator. **Bellwether** is a regime-adaptive,
> risk-managed trading **signal** engine for the terminal: it turns *real* market
> data into actionable `BUY` / `SELL` / `HOLD` calls with explicit math behind
> every decision.

```
================================================================================
BELLWETHER_v0.1.0 // ACTIVE // PORTFOLIO_VALUE: $100,000.00 // DAILY_P&L: +0.00%
================================================================================

[MARKET SCAN RECONNAISSANCE]
Target Ticker: NVDA
Current Price: $128.50
Market Regime: High-Velocity Aggressive Up-Trend (ADX 41.2, ATR 3.10%, Vol: elevated)

[ALGORITHM ENGINE SELECTION]
Selected Framework: Multi-Timeframe Quantitative Momentum (EMA-20/50 + RSI)
Reasoning: EMA-20 above EMA-50 by 2.10%; ADX 41.2 confirms trend; RSI 63.4 has room to run.
Conviction: 0.71

[RISK MITIGATION SPECIFICATIONS]
Calculated Risk Ratio: 0.0097 (0.97% portfolio risk)
Calculated Stop-Loss: $122.30
Calculated Take-Profit: $137.80
Target Position Size: 156 units (notional $20,046.00)

[EXECUTION COMMAND]
--------------------------------------------------------------------------------
ORDER_SIGNAL : BUY
TICKER       : NVDA
VOLUME       : 156 SHARES
ENTRY_LIMIT  : $128.50
TIMESTAMP    : 2026-06-03 22:54:00 UTC
--------------------------------------------------------------------------------
```

## ⚠️ What this is (and isn't)

Bellwether emits **text-based signals and a paper-trading ledger**. It does **not**
place real orders and holds no broker credentials — actual execution requires you
to bridge the output (terminal piping or manual broker entry). It is a research
and education tool, **not financial advice**.

Critically, Bellwether **never fabricates prices**. Every number on screen comes
from a live data pull. If a feed is empty, too short, stale, or has NaNs in the
latest bar, the engine raises a `DataGap`, logs `[ERROR: DATA_GAP]`, and skips
that asset rather than guessing.

## Install

```bash
cd bellwether
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .          # optional: exposes the `bellwether` command
```

## Usage

```bash
# Scan a pool and print signals (read-only, no portfolio changes)
python -m bellwether scan NVDA AAPL MSFT SPY

# Longer history / different bar size
python -m bellwether scan --period 1y --interval 1d QQQ TSLA

# Apply signals to the persistent paper portfolio (simulated fills, stops, targets)
python -m bellwether scan --apply NVDA AAPL

# Inspect / reset the paper book
python -m bellwether status
python -m bellwether reset --capital 250000
```

Portfolio state persists at `~/.bellwether/portfolio.json`.

## How it decides

| Stage | Module | Logic |
|-------|--------|-------|
| **Data** | `data.py` | Pull real OHLCV (Yahoo via `yfinance`); strict integrity gating → `DataGap` |
| **Regime** | `regime.py` | ADX → trend strength, ATR% → volatility, EMA-20/50 → direction |
| **Strategy** | `strategy.py` | Trending → Quant Momentum; Ranging → Bollinger %B Mean Reversion |
| **Risk** | `risk.py` | Volatility-scaled risk ratio, ATR-anchored stops, no-leverage sizing |
| **Guardrail** | `risk.py` | Hard **2% daily-loss circuit breaker** freezes new BUYs |

### Position sizing

```
size = (capital × risk_ratio) / |entry − stop|
```

The `risk_ratio` (base **1.5%**) is scaled **down** as ATR% rises above a 2%
reference and floored at **0.5%**, so the engine automatically bets smaller into
volatile tape. Stops and targets are multiples of ATR, so they breathe with each
asset's own volatility instead of arbitrary fixed percentages.

### Circuit breaker

If mark-to-market daily P&L breaches **−2%** of the day's starting equity, the
engine prints `[CRITICAL: CIRCUIT_BREAKER_TRIGGERED]`, freezes all new BUYs for
the session, and permits only SELL/HOLD.

## Tests

```bash
pip install pytest
pytest -q
```

Indicator math and the full risk/sizing/portfolio layer are unit-tested offline
(no network required).

## Layout

```
bellwether/
  data.py        # real OHLCV + data-integrity gating
  indicators.py  # SMA/EMA, ATR, RSI, Bollinger, ADX (numpy/pandas)
  regime.py      # market-regime classification
  strategy.py    # framework selection + signal generation
  risk.py        # volatility-adjusted sizing + circuit breaker
  portfolio.py   # JSON-persisted paper ledger
  dashboard.py   # terminal rendering
  engine.py      # scan orchestration
  cli.py         # argparse CLI
tests/           # offline unit tests
```

## License

MIT
