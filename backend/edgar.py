"""SEC EDGAR integration: fetch recent filings to enrich research prompts."""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from .config import CACHE_DIR

# SEC requires a User-Agent header with contact info
_USER_AGENT = os.getenv("SEC_USER_AGENT", "llm-council research-bot contact@example.com")
_EDGAR_BASE = "https://data.sec.gov"
_TICKERS_URL = f"{_EDGAR_BASE}/files/company_tickers.json"
_TICKERS_CACHE = os.path.join(CACHE_DIR, "__sec_tickers.json")
_TICKERS_TTL = 86400 * 7  # refresh weekly

_FILING_TYPES = {"10-K", "10-Q", "8-K"}


def _sec_headers() -> Dict[str, str]:
    return {"User-Agent": _USER_AGENT, "Accept": "application/json"}


def _cache_get_raw(path: str, ttl: int) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r") as f:
            entry = json.load(f)
        if time.time() - entry.get("fetched_at", 0) <= ttl:
            return entry["payload"]
    except (json.JSONDecodeError, OSError, KeyError):
        pass
    return None


def _cache_put_raw(path: str, payload: Any):
    Path(CACHE_DIR).mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump({"fetched_at": time.time(), "payload": payload}, f)


async def _get_ticker_map() -> Dict[str, str]:
    """Return mapping of ticker → CIK (zero-padded 10-digit string)."""
    cached = _cache_get_raw(_TICKERS_CACHE, _TICKERS_TTL)
    if cached:
        return cached

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(_TICKERS_URL, headers=_sec_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"SEC ticker map fetch failed: {e}")
        return {}

    # data is {index: {cik_str, ticker, title}}
    ticker_map = {
        v["ticker"].upper(): str(v["cik_str"]).zfill(10)
        for v in data.values()
        if "ticker" in v and "cik_str" in v
    }
    _cache_put_raw(_TICKERS_CACHE, ticker_map)
    return ticker_map


async def _get_cik(ticker: str) -> Optional[str]:
    tmap = await _get_ticker_map()
    return tmap.get(ticker.upper())


async def get_recent_filings(ticker: str, limit: int = 5) -> List[Dict[str, Any]]:
    """
    Fetch the most recent 10-K, 10-Q, and 8-K filings for a ticker.
    Returns list of {type, date, description, url}.
    Cached per ticker for 24h.
    """
    cache_path = os.path.join(CACHE_DIR, f"{ticker.upper()}__edgar.json")
    cached = _cache_get_raw(cache_path, 86400)
    if cached is not None:
        return cached

    cik = await _get_cik(ticker)
    if not cik:
        return []

    url = f"{_EDGAR_BASE}/submissions/CIK{cik}.json"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers=_sec_headers())
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        print(f"SEC filings fetch failed for {ticker}: {e}")
        return []

    recent = data.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    descriptions = recent.get("primaryDocument", [])
    accessions = recent.get("accessionNumber", [])

    filings = []
    for form, date, desc, acc in zip(forms, dates, descriptions, accessions):
        if form in _FILING_TYPES:
            acc_clean = acc.replace("-", "")
            filing_url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc_clean}/{desc}"
            filings.append({
                "type": form,
                "date": date,
                "description": desc,
                "url": filing_url,
            })
        if len(filings) >= limit:
            break

    _cache_put_raw(cache_path, filings)
    return filings


def format_filings_for_prompt(filings: List[Dict[str, Any]]) -> str:
    if not filings:
        return "(no recent SEC filings found)"
    lines = []
    for f in filings:
        lines.append(f"- [{f['date']}] {f['type']}: {f['description']} → {f['url']}")
    return "\n".join(lines)
