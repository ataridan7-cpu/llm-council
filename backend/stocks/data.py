"""Market data layer: batched yfinance download with an on-disk cache,
strict point-in-time snapshots, and live-only extras.

Point-in-time discipline: historical simulation runs may ONLY see features
computed from prices.loc[:as_of]. Fundamentals (Ticker.info) and news are
current-state in yfinance — never point-in-time — so they are exposed only
through build_live_extras() and must never be fed to historical runs.
"""

import json
import os
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import pandas as pd

from .config import (
    TICKERS,
    BENCHMARK,
    PRICES_CACHE_CSV,
    CACHE_META_JSON,
    PRICE_CACHE_MAX_AGE_HOURS,
)

# Need ~14 months of history before the oldest sim date for 12-month
# lookback features; 420 days of padding covers it
LOOKBACK_PADDING_DAYS = 420


def _cache_age_hours() -> Optional[float]:
    if not os.path.exists(CACHE_META_JSON):
        return None
    try:
        with open(CACHE_META_JSON) as f:
            meta = json.load(f)
        fetched_at = datetime.fromisoformat(meta["fetched_at"])
        return (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600
    except Exception:
        return None


def load_cached_prices() -> Optional[pd.DataFrame]:
    if not os.path.exists(PRICES_CACHE_CSV):
        return None
    df = pd.read_csv(PRICES_CACHE_CSV, index_col=0, parse_dates=True)
    df.index.name = "Date"
    return df


def save_prices_cache(prices: pd.DataFrame, source: str) -> None:
    os.makedirs(os.path.dirname(PRICES_CACHE_CSV), exist_ok=True)
    prices.to_csv(PRICES_CACHE_CSV)
    with open(CACHE_META_JSON, "w") as f:
        json.dump(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "tickers": list(prices.columns),
                "start": str(prices.index.min().date()),
                "end": str(prices.index.max().date()),
            },
            f,
            indent=2,
        )


def fetch_prices_from_yahoo(
    tickers: Optional[List[str]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
) -> pd.DataFrame:
    """One batched download of adjusted closes for all tickers + benchmark.

    All point-in-time slicing happens locally on the cached frame, which
    both avoids Yahoo rate limits and keeps PIT discipline auditable.
    """
    import yfinance as yf

    tickers = tickers or (TICKERS + [BENCHMARK])
    if BENCHMARK not in tickers:
        tickers = tickers + [BENCHMARK]
    start = start or (date.today() - timedelta(days=365 + LOOKBACK_PADDING_DAYS))
    end = end or date.today() + timedelta(days=1)

    raw = yf.download(
        tickers,
        start=str(start),
        end=str(end),
        auto_adjust=True,
        progress=False,
        group_by="column",
    )
    if raw is None or len(raw) == 0:
        raise RuntimeError("yfinance returned no data")

    closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    closes = closes.dropna(how="all")
    # Tolerate sparse per-ticker gaps but never fill across a leading void
    closes = closes.ffill(limit=5)
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    closes.index.name = "Date"
    return closes


def get_prices(force_refresh: bool = False) -> pd.DataFrame:
    """Cached prices, refreshed from Yahoo when stale. Falls back to the
    existing cache if the network fetch fails."""
    cached = load_cached_prices()
    age = _cache_age_hours()
    fresh = age is not None and age < PRICE_CACHE_MAX_AGE_HOURS
    if cached is not None and fresh and not force_refresh:
        return cached
    try:
        prices = fetch_prices_from_yahoo()
        save_prices_cache(prices, source="yahoo")
        return prices
    except Exception as e:
        if cached is not None:
            print(f"Price refresh failed ({e}); using stale cache")
            return cached
        raise


def snap_to_trading_day(d: date, index: pd.DatetimeIndex) -> pd.Timestamp:
    """Last trading day <= d. Handles weekends/holidays."""
    ts = pd.Timestamp(d)
    snapped = index.asof(ts)
    if pd.isna(snapped):
        raise ValueError(f"No trading day on or before {d} in price history")
    return snapped


def _pct(a: float, b: float) -> Optional[float]:
    if b is None or pd.isna(b) or b == 0 or a is None or pd.isna(a):
        return None
    return round((a / b - 1) * 100, 2)


def build_snapshot(ticker: str, as_of: date, prices: pd.DataFrame) -> Dict[str, Any]:
    """Price-derived features computed strictly from data on or before as_of."""
    if ticker not in prices.columns:
        return {"ticker": ticker, "error": "no price data"}

    series = prices[ticker].dropna()
    asof_ts = snap_to_trading_day(as_of, series.index)
    # The PIT guarantee: nothing after as_of is visible from here on
    hist = series.loc[:asof_ts]
    if len(hist) < 30:
        return {"ticker": ticker, "error": "insufficient history"}

    last_close = float(hist.iloc[-1])

    def close_n_days_back(n: int) -> Optional[float]:
        cutoff = asof_ts - pd.Timedelta(days=n)
        window = hist.loc[:cutoff]
        return float(window.iloc[-1]) if len(window) else None

    year = hist.loc[asof_ts - pd.Timedelta(days=365):]
    high_52w = float(year.max())
    low_52w = float(year.min())
    daily_ret = hist.pct_change().dropna()
    vol_60d = (
        round(float(daily_ret.tail(60).std() * (252 ** 0.5)) * 100, 1)
        if len(daily_ret) >= 20
        else None
    )
    running_max = year.cummax()
    max_drawdown = round(float(((year / running_max) - 1).min()) * 100, 1)

    return {
        "ticker": ticker,
        "as_of_trading_day": str(asof_ts.date()),
        "last_close": round(last_close, 2),
        "return_1m_pct": _pct(last_close, close_n_days_back(30)),
        "return_3m_pct": _pct(last_close, close_n_days_back(91)),
        "return_6m_pct": _pct(last_close, close_n_days_back(182)),
        "return_12m_pct": _pct(last_close, close_n_days_back(365)),
        "pct_below_52w_high": _pct(last_close, high_52w),
        "pct_above_52w_low": _pct(last_close, low_52w),
        "realized_vol_60d_annualized_pct": vol_60d,
        "max_drawdown_12m_pct": max_drawdown,
    }


def build_live_extras(ticker: str, max_news: int = 5) -> Dict[str, Any]:
    """Current fundamentals + recent headlines. LIVE RUNS ONLY — this data
    is not point-in-time and must never feed a historical simulation."""
    import yfinance as yf

    extras: Dict[str, Any] = {"ticker": ticker}
    try:
        t = yf.Ticker(ticker)
        info = t.info or {}
        for key, label in [
            ("trailingPE", "trailing_pe"),
            ("forwardPE", "forward_pe"),
            ("marketCap", "market_cap"),
            ("profitMargins", "profit_margin"),
            ("revenueGrowth", "revenue_growth"),
            ("shortPercentOfFloat", "short_pct_of_float"),
        ]:
            if info.get(key) is not None:
                extras[label] = info[key]
        headlines = []
        for item in (t.news or [])[:max_news]:
            content = item.get("content", item)
            title = content.get("title")
            when = content.get("pubDate") or content.get("providerPublishTime")
            if title:
                headlines.append({"title": title, "published": str(when)})
        if headlines:
            extras["recent_headlines"] = headlines
    except Exception as e:
        extras["error"] = f"live extras unavailable: {e}"
    return extras


def generate_synthetic_prices(
    tickers: Optional[List[str]] = None,
    start: Optional[date] = None,
    end: Optional[date] = None,
    seed: int = 42,
) -> pd.DataFrame:
    """Deterministic geometric-Brownian price paths on business days.
    For tests and demo seeding only — clearly not real market data."""
    import numpy as np

    tickers = tickers or (TICKERS + [BENCHMARK])
    start = start or (date.today() - timedelta(days=365 + LOOKBACK_PADDING_DAYS))
    end = end or date.today()
    index = pd.bdate_range(str(start), str(end))
    rng = np.random.RandomState(seed)
    data = {}
    for i, ticker in enumerate(sorted(tickers)):
        drift = 0.0002 + 0.0004 * ((i % 5) - 2)
        vol = 0.012 + 0.004 * (i % 4)
        rets = rng.normal(drift, vol, size=len(index))
        data[ticker] = 100.0 * (1 + pd.Series(rets, index=index)).cumprod()
    df = pd.DataFrame(data)[tickers]
    df.index.name = "Date"
    return df
