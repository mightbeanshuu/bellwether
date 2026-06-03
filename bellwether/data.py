"""Market data access + strict data-integrity gating.

Bellwether pulls *real* OHLCV from pluggable sources:

  * ``yahoo``        — equities/ETFs via yfinance (e.g. NVDA, SPY)
  * ``coinex``       — CoinEx USDT-perpetual futures (e.g. BTCUSDT)  [default crypto]
  * ``coinex-spot``  — CoinEx spot markets

The engine never fabricates or forward-fills missing prices: if a feed is empty,
too short, stale, or returns NaNs in the tail, we raise DataGap so the engine can
log the error and skip the asset instead of trading on bad data.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd

# Bars required before indicators (EMA-50, ADX-14, BB-20) are trustworthy.
MIN_BARS = 60

# Seconds per bar, keyed by the CLI's interval shorthand.
INTERVAL_SECONDS = {
    "1m": 60, "3m": 180, "5m": 300, "15m": 900, "30m": 1800,
    "1h": 3600, "2h": 7200, "4h": 14400, "6h": 21600, "12h": 43200,
    "1d": 86400, "3d": 259200, "1w": 604800,
}

# CLI interval shorthand -> CoinEx period strings.
COINEX_PERIOD = {
    "1m": "1min", "3m": "3min", "5m": "5min", "15m": "15min", "30m": "30min",
    "1h": "1hour", "2h": "2hour", "4h": "4hour", "6h": "6hour", "12h": "12hour",
    "1d": "1day", "3d": "3day", "1w": "1week",
}

COINEX_BASE = "https://api.coinex.com/v2"
_OHLCV = ["Open", "High", "Low", "Close", "Volume"]


class DataGap(Exception):
    """Raised when a feed is incomplete, stale, or otherwise untrustworthy."""


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def _validate(df: pd.DataFrame, symbol: str, max_staleness_seconds: float) -> pd.DataFrame:
    if df is None or df.empty:
        raise DataGap(f"{symbol}: empty feed (no rows returned).")

    missing = set(_OHLCV) - set(df.columns)
    if missing:
        raise DataGap(f"{symbol}: feed missing columns {sorted(missing)}.")

    df = df[_OHLCV].dropna()
    if len(df) < MIN_BARS:
        raise DataGap(f"{symbol}: only {len(df)} clean bars (<{MIN_BARS} required).")

    if df[["High", "Low", "Close"]].iloc[-1].isna().any():
        raise DataGap(f"{symbol}: NaN in most recent bar.")

    last = pd.Timestamp(df.index[-1]).tz_localize(None).to_pydatetime()
    age = (datetime.now(timezone.utc).replace(tzinfo=None) - last).total_seconds()
    if age > max_staleness_seconds:
        raise DataGap(
            f"{symbol}: latest bar is {age/3600:.1f}h stale "
            f"(>{max_staleness_seconds/3600:.1f}h limit)."
        )
    return df


# --------------------------------------------------------------------------
# Yahoo Finance (equities / ETFs)
# --------------------------------------------------------------------------
def _import_yfinance():
    try:
        import logging

        import yfinance as yf  # noqa: WPS433 (lazy import keeps tests offline)

        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    except ImportError as exc:  # pragma: no cover
        raise DataGap(
            "yfinance is not installed — run `pip install -r requirements.txt`."
        ) from exc
    return yf


def _fetch_yahoo(ticker: str, period: str, interval: str) -> pd.DataFrame:
    yf = _import_yfinance()
    raw = yf.download(
        ticker, period=period, interval=interval,
        progress=False, auto_adjust=True, multi_level_index=False,
    )
    if raw is None or raw.empty:
        raise DataGap(f"{ticker}: empty feed (no rows returned).")
    # Stocks don't trade weekends/holidays, so allow up to 5 calendar days.
    return _validate(raw, ticker, max_staleness_seconds=5 * 86400)


# --------------------------------------------------------------------------
# CoinEx (crypto futures / spot)
# --------------------------------------------------------------------------
def _http_get_json(path: str, params: dict, timeout: int = 12) -> dict:
    url = f"{COINEX_BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "bellwether/0.2"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except Exception as exc:  # network / decode failures are data gaps
        raise DataGap(f"CoinEx request failed: {exc}") from exc
    if payload.get("code") != 0:
        raise DataGap(f"CoinEx API error: {payload.get('message', 'unknown')}")
    return payload


def _fetch_coinex(market: str, interval: str, bars: int, segment: str) -> pd.DataFrame:
    period = COINEX_PERIOD.get(interval)
    if period is None:
        raise DataGap(f"{market}: unsupported interval '{interval}' for CoinEx.")

    payload = _http_get_json(
        f"/{segment}/kline",
        {"market": market, "period": period, "limit": min(max(bars, MIN_BARS + 5), 1000)},
    )
    rows = payload.get("data") or []
    if not rows:
        raise DataGap(f"{market}: empty feed (no rows returned).")

    df = pd.DataFrame(rows)
    df["created_at"] = pd.to_datetime(df["created_at"], unit="ms")
    df = df.set_index("created_at").sort_index()
    df = df.rename(columns={
        "open": "Open", "high": "High", "low": "Low",
        "close": "Close", "volume": "Volume",
    })
    for col in _OHLCV:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # CoinEx returns the in-progress candle last; allow ~3 bar-widths of lag.
    bar_seconds = INTERVAL_SECONDS.get(interval, 86400)
    return _validate(df, market, max_staleness_seconds=max(3 * bar_seconds, 120))


# --------------------------------------------------------------------------
# Public dispatch
# --------------------------------------------------------------------------
def fetch(
    symbol: str,
    source: str = "yahoo",
    period: str = "6mo",
    interval: str = "1d",
    bars: int = 500,
) -> pd.DataFrame:
    """Fetch a clean OHLCV frame for `symbol` from `source`, or raise DataGap."""
    if source == "yahoo":
        return _fetch_yahoo(symbol, period, interval)
    if source in ("coinex", "coinex-futures"):
        return _fetch_coinex(symbol, interval, bars, "futures")
    if source == "coinex-spot":
        return _fetch_coinex(symbol, interval, bars, "spot")
    raise DataGap(f"{symbol}: unknown data source '{source}'.")


def latest_price(df: pd.DataFrame) -> float:
    return float(df["Close"].iloc[-1])


# --------------------------------------------------------------------------
# Live quotes (lightweight, for the real-time ticker strip)
# --------------------------------------------------------------------------
@dataclass
class Quote:
    symbol: str
    last: float
    open_24h: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0

    @property
    def change_pct(self) -> float:
        return (self.last - self.open_24h) / self.open_24h if self.open_24h else 0.0


def _coinex_quotes(symbols: list[str], segment: str) -> dict[str, Quote]:
    try:
        payload = _http_get_json(f"/{segment}/ticker", {"market": ",".join(symbols)})
    except DataGap:
        return {}
    out: dict[str, Quote] = {}
    for r in payload.get("data", []):
        try:
            out[r["market"]] = Quote(
                symbol=r["market"],
                last=float(r["last"]),
                open_24h=float(r.get("open") or 0),
                high=float(r.get("high") or 0),
                low=float(r.get("low") or 0),
                volume=float(r.get("volume") or 0),
            )
        except (KeyError, ValueError, TypeError):
            continue
    return out


def _yahoo_quotes(symbols: list[str]) -> dict[str, Quote]:
    yf = _import_yfinance()
    out: dict[str, Quote] = {}
    for sym in symbols:
        try:
            fi = yf.Ticker(sym).fast_info
            last = float(fi.get("last_price") or fi.get("lastPrice") or 0)
            prev = float(fi.get("previous_close") or fi.get("previousClose") or last)
            if not last:
                continue
            out[sym] = Quote(
                symbol=sym, last=last, open_24h=prev,
                high=float(fi.get("day_high") or 0), low=float(fi.get("day_low") or 0),
                volume=float(fi.get("last_volume") or 0),
            )
        except Exception:
            continue
    return out


def quotes(symbols: list[str], source: str = "coinex") -> dict[str, Quote]:
    """Fast last-price quotes (+24h change) for a live ticker. Best-effort: a
    failed feed yields an empty/partial map rather than raising."""
    if source in ("coinex", "coinex-futures"):
        return _coinex_quotes(symbols, "futures")
    if source == "coinex-spot":
        return _coinex_quotes(symbols, "spot")
    if source == "yahoo":
        return _yahoo_quotes(symbols)
    return {}
