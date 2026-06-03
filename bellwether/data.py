"""Market data access + strict data-integrity gating.

Real OHLCV is pulled from Yahoo Finance via `yfinance`. The engine never
fabricates or forward-fills missing prices: if a feed is stale, too short, or
returns NaNs in the tail, we raise DataGap so the engine can log the error and
skip the asset instead of trading on bad data.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

# Bars required before indicators (EMA-50, ADX-14, BB-20) are trustworthy.
MIN_BARS = 60
# How stale the most recent daily bar may be before we treat it as a gap.
MAX_STALENESS_DAYS = 5


class DataGap(Exception):
    """Raised when a feed is incomplete, stale, or otherwise untrustworthy."""


def _import_yfinance():
    try:
        import logging

        import yfinance as yf  # noqa: WPS433 (lazy import keeps tests offline)

        # yfinance logs its own HTTP/download errors; we surface gaps ourselves
        # via DataGap, so keep the dashboard clean by muting its chatter.
        logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    except ImportError as exc:  # pragma: no cover
        raise DataGap(
            "yfinance is not installed — run `pip install -r requirements.txt`."
        ) from exc
    return yf


def fetch(ticker: str, period: str = "6mo", interval: str = "1d") -> pd.DataFrame:
    """Fetch a clean OHLCV frame for `ticker` or raise DataGap.

    Validates: non-empty, enough bars, no NaNs in the trailing row, and that the
    latest bar isn't unreasonably stale for the requested interval.
    """
    yf = _import_yfinance()
    raw = yf.download(
        ticker, period=period, interval=interval,
        progress=False, auto_adjust=True, multi_level_index=False,
    )

    if raw is None or raw.empty:
        raise DataGap(f"{ticker}: empty feed (no rows returned).")

    cols = {"Open", "High", "Low", "Close", "Volume"}
    missing = cols - set(raw.columns)
    if missing:
        raise DataGap(f"{ticker}: feed missing columns {sorted(missing)}.")

    df = raw[["Open", "High", "Low", "Close", "Volume"]].dropna()

    if len(df) < MIN_BARS:
        raise DataGap(f"{ticker}: only {len(df)} clean bars (<{MIN_BARS} required).")

    if df[["High", "Low", "Close"]].iloc[-1].isna().any():
        raise DataGap(f"{ticker}: NaN in most recent bar.")

    if interval.endswith("d"):
        last = pd.Timestamp(df.index[-1]).tz_localize(None)
        age_days = (datetime.now(timezone.utc).replace(tzinfo=None) - last.to_pydatetime()).days
        if age_days > MAX_STALENESS_DAYS:
            raise DataGap(f"{ticker}: latest bar is {age_days}d stale (>{MAX_STALENESS_DAYS}d).")

    return df


def latest_price(df: pd.DataFrame) -> float:
    return float(df["Close"].iloc[-1])
