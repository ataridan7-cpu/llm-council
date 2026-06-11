"""Market data fetching via yfinance, with a TTL file cache."""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import yfinance as yf

from .config import CACHE_DIR, CACHE_TTLS


def _cache_path(key: str) -> str:
    return os.path.join(CACHE_DIR, f"{key}.json")


def _cache_get(key: str, ttl: int, allow_stale: bool = False) -> Optional[Dict[str, Any]]:
    path = _cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            entry = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    age = time.time() - entry.get("fetched_at", 0)
    if age <= ttl:
        return entry["payload"]
    if allow_stale:
        payload = entry["payload"]
        if isinstance(payload, dict):
            payload = {**payload, "stale": True}
        return payload
    return None


def _cache_put(key: str, payload: Any):
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    with open(_cache_path(key), 'w') as f:
        json.dump({"fetched_at": time.time(), "payload": payload}, f)


async def _fetch_with_retry(fn, *args):
    """Run a sync yfinance call in a thread, retrying once on failure."""
    for attempt in range(2):
        try:
            return await asyncio.to_thread(fn, *args)
        except Exception as e:
            if attempt == 0:
                await asyncio.sleep(1.5)
            else:
                print(f"Market data fetch failed: {e}")
    return None


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper()


def _fetch_quote(ticker: str) -> Optional[Dict[str, Any]]:
    info = yf.Ticker(ticker).info or {}
    price = info.get("regularMarketPrice") or info.get("currentPrice")
    if price is None:
        return None
    return {
        "ticker": ticker,
        "name": info.get("longName") or info.get("shortName") or ticker,
        "price": price,
        "prev_close": info.get("regularMarketPreviousClose") or info.get("previousClose"),
        "currency": info.get("currency", "USD"),
        "market_cap": info.get("marketCap"),
        "as_of": datetime.utcnow().isoformat(),
    }


async def get_quote(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = _normalize_ticker(ticker)
    key = f"{ticker}__quote"
    cached = _cache_get(key, CACHE_TTLS["quote"])
    if cached is not None:
        return cached
    quote = await _fetch_with_retry(_fetch_quote, ticker)
    if quote is not None:
        _cache_put(key, quote)
        return quote
    return _cache_get(key, CACHE_TTLS["quote"], allow_stale=True)


def _fetch_history(ticker: str, period: str, interval: str) -> Optional[Dict[str, Any]]:
    df = yf.Ticker(ticker).history(period=period, interval=interval)
    if df is None or df.empty:
        return None
    candles = []
    for idx, row in df.iterrows():
        candles.append({
            "date": idx.strftime("%Y-%m-%d"),
            "open": round(float(row["Open"]), 4),
            "high": round(float(row["High"]), 4),
            "low": round(float(row["Low"]), 4),
            "close": round(float(row["Close"]), 4),
            "volume": int(row["Volume"]),
        })
    return {"ticker": ticker, "period": period, "interval": interval, "candles": candles}


async def get_price_history(
    ticker: str, period: str = "1y", interval: str = "1d"
) -> Optional[Dict[str, Any]]:
    ticker = _normalize_ticker(ticker)
    key = f"{ticker}__history_{period}_{interval}"
    cached = _cache_get(key, CACHE_TTLS["history"])
    if cached is not None:
        return cached
    history = await _fetch_with_retry(_fetch_history, ticker, period, interval)
    if history is not None:
        _cache_put(key, history)
        return history
    return _cache_get(key, CACHE_TTLS["history"], allow_stale=True)


# Curated Ticker.info keys worth sending to the fundamentals analyst
_FUNDAMENTAL_KEYS = [
    "longName", "sector", "industry", "marketCap", "enterpriseValue",
    "trailingPE", "forwardPE", "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToEbitda", "pegRatio", "trailingEps", "forwardEps",
    "totalRevenue", "revenueGrowth", "earningsGrowth", "grossMargins",
    "operatingMargins", "profitMargins", "returnOnEquity", "returnOnAssets",
    "totalCash", "totalDebt", "debtToEquity", "currentRatio", "quickRatio",
    "freeCashflow", "operatingCashflow", "dividendYield", "payoutRatio",
    "beta", "sharesOutstanding", "heldPercentInsiders", "heldPercentInstitutions",
    "shortPercentOfFloat", "recommendationKey", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
]


def _fetch_fundamentals(ticker: str) -> Optional[Dict[str, Any]]:
    info = yf.Ticker(ticker).info or {}
    if not info.get("regularMarketPrice") and not info.get("currentPrice"):
        return None
    return {k: info[k] for k in _FUNDAMENTAL_KEYS if info.get(k) is not None}


async def get_fundamentals(ticker: str) -> Optional[Dict[str, Any]]:
    ticker = _normalize_ticker(ticker)
    key = f"{ticker}__fundamentals"
    cached = _cache_get(key, CACHE_TTLS["fundamentals"])
    if cached is not None:
        return cached
    fundamentals = await _fetch_with_retry(_fetch_fundamentals, ticker)
    if fundamentals is not None:
        _cache_put(key, fundamentals)
        return fundamentals
    return _cache_get(key, CACHE_TTLS["fundamentals"], allow_stale=True)


def _fetch_news(ticker: str, limit: int) -> List[Dict[str, Any]]:
    items = yf.Ticker(ticker).news or []
    news = []
    for item in items[:limit]:
        # yfinance >= 0.2.50 nests fields under "content"
        content = item.get("content", item)
        pub_date = content.get("pubDate") or content.get("providerPublishTime")
        if isinstance(pub_date, (int, float)):
            pub_date = datetime.utcfromtimestamp(pub_date).isoformat()
        provider = content.get("provider") or {}
        news.append({
            "title": content.get("title", ""),
            "publisher": provider.get("displayName") if isinstance(provider, dict) else str(provider),
            "published_at": pub_date,
            "summary": content.get("summary", ""),
            "link": (content.get("canonicalUrl") or {}).get("url") if isinstance(content.get("canonicalUrl"), dict) else content.get("link"),
        })
    return news


async def get_news(ticker: str, limit: int = 15) -> List[Dict[str, Any]]:
    ticker = _normalize_ticker(ticker)
    key = f"{ticker}__news"
    cached = _cache_get(key, CACHE_TTLS["news"])
    if cached is not None:
        return cached
    news = await _fetch_with_retry(_fetch_news, ticker, limit)
    if news is not None:
        _cache_put(key, news)
        return news
    stale = _cache_get(key, CACHE_TTLS["news"], allow_stale=True)
    return stale if isinstance(stale, list) else []


def _sma(closes: List[float], window: int) -> Optional[float]:
    if len(closes) < window:
        return None
    return round(sum(closes[-window:]) / window, 4)


def _rsi(closes: List[float], window: int = 14) -> Optional[float]:
    if len(closes) < window + 1:
        return None
    gains, losses = [], []
    for prev, curr in zip(closes[-(window + 1):-1], closes[-window:]):
        change = curr - prev
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / window
    avg_loss = sum(losses) / window
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100 - 100 / (1 + rs), 2)


def _trailing_return(closes: List[float], trading_days: int) -> Optional[float]:
    if len(closes) <= trading_days:
        return None
    return round(closes[-1] / closes[-1 - trading_days] - 1, 4)


def compute_indicators(candles: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute technical indicators from daily candles (pure python)."""
    closes = [c["close"] for c in candles]
    volumes = [c["volume"] for c in candles]
    if not closes:
        return {}
    return {
        "last_close": closes[-1],
        "sma20": _sma(closes, 20),
        "sma50": _sma(closes, 50),
        "sma200": _sma(closes, 200),
        "rsi14": _rsi(closes),
        "high_52w": max(c["high"] for c in candles),
        "low_52w": min(c["low"] for c in candles),
        "return_1w": _trailing_return(closes, 5),
        "return_1m": _trailing_return(closes, 21),
        "return_3m": _trailing_return(closes, 63),
        "avg_volume_20d": int(sum(volumes[-20:]) / min(len(volumes), 20)) if volumes else None,
    }


def _fetch_close_on_or_after(ticker: str, date: str) -> Optional[Dict[str, Any]]:
    start = datetime.fromisoformat(date[:10])
    end = start + timedelta(days=10)
    df = yf.Ticker(ticker).history(
        start=start.strftime("%Y-%m-%d"), end=end.strftime("%Y-%m-%d"), interval="1d"
    )
    if df is None or df.empty:
        return None
    idx = df.index[0]
    return {"date": idx.strftime("%Y-%m-%d"), "close": round(float(df.iloc[0]["Close"]), 4)}


async def get_close_on_or_after(ticker: str, date: str) -> Optional[Dict[str, Any]]:
    """First available daily close on or after the given ISO date (for scoring)."""
    ticker = _normalize_ticker(ticker)
    return await _fetch_with_retry(_fetch_close_on_or_after, ticker, date)
