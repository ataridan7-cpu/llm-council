"""Stage 0: specialist research agents that build the market dossier."""

import asyncio
import json
from typing import Any, Dict, List, Optional

from .config import RESEARCH_MODELS
from .market_data import (
    compute_indicators,
    get_fundamentals,
    get_news,
    get_price_history,
    get_quote,
)
from .openrouter import query_model

ROLE_TITLES = {
    "fundamentals": "Fundamentals Analyst",
    "technical": "Technical Analyst",
    "news": "News & Sentiment Analyst",
}

_SHARED_RULES = """Rules:
- Analysis only. Do NOT give a buy/hold/sell recommendation or price targets - an investment council makes that decision based on your report.
- Be specific and quantitative; cite the numbers you were given.
- Keep the report under 800 words.
- Use the exact markdown section headings specified, and end with a "## Key Takeaways" section of 3-5 bullets."""


async def gather_market_data(ticker: str) -> Dict[str, Any]:
    """
    Fetch all market data for a ticker in parallel.

    Raises:
        ValueError: if the ticker is invalid (no quote available)
    """
    quote, history, fundamentals, news = await asyncio.gather(
        get_quote(ticker),
        get_price_history(ticker, period="1y", interval="1d"),
        get_fundamentals(ticker),
        get_news(ticker),
    )
    if quote is None:
        raise ValueError(f"Unknown ticker or no market data available: {ticker}")

    candles = history["candles"] if history else []
    return {
        "ticker": ticker.strip().upper(),
        "quote": quote,
        "candles": candles,
        "indicators": compute_indicators(candles) if candles else {},
        "fundamentals": fundamentals or {},
        "news": news or [],
    }


def _candles_table(candles: List[Dict[str, Any]], limit: int = 60) -> str:
    rows = ["date | open | high | low | close | volume"]
    for c in candles[-limit:]:
        rows.append(
            f"{c['date']} | {c['open']} | {c['high']} | {c['low']} | {c['close']} | {c['volume']}"
        )
    return "\n".join(rows)


def _news_digest(news: List[Dict[str, Any]]) -> str:
    if not news:
        return "(no recent news found)"
    items = []
    for n in news:
        line = f"- [{n.get('published_at', '?')}] {n.get('title', '')} ({n.get('publisher', '?')})"
        summary = (n.get('summary') or '').strip()
        if summary:
            line += f"\n  {summary[:400]}"
        items.append(line)
    return "\n".join(items)


def _build_role_prompt(role: str, ticker: str, data: Dict[str, Any]) -> str:
    quote = data["quote"]
    header = (
        f"You are the {ROLE_TITLES[role]} on a stock research team analyzing "
        f"{quote.get('name', ticker)} ({ticker}). "
        f"Current price: {quote['price']} {quote.get('currency', 'USD')} as of {quote.get('as_of')}.\n\n"
    )

    if role == "fundamentals":
        body = (
            "Company fundamentals (from market data):\n"
            f"{json.dumps(data['fundamentals'], indent=2)}\n\n"
            "Key technical context:\n"
            f"{json.dumps(data['indicators'], indent=2)}\n\n"
            "Write a fundamentals report with these sections:\n"
            "## Valuation\n## Growth & Profitability\n## Balance Sheet & Cash Flow\n## Red Flags\n## Key Takeaways"
        )
    elif role == "technical":
        body = (
            "Technical indicators:\n"
            f"{json.dumps(data['indicators'], indent=2)}\n\n"
            "Recent daily candles (last 60 trading days):\n"
            f"{_candles_table(data['candles'])}\n\n"
            "Write a technical analysis report with these sections:\n"
            "## Trend & Momentum\n## Support & Resistance\n## Volume Analysis\n## Notable Patterns\n## Key Takeaways"
        )
    else:  # news
        body = (
            "Recent news headlines and summaries:\n"
            f"{_news_digest(data['news'])}\n\n"
            "Write a news & sentiment report with these sections:\n"
            "## Major Developments\n## Sentiment Assessment\n## Catalysts & Upcoming Events\n## Key Takeaways"
        )

    return f"{header}{body}\n\n{_SHARED_RULES}"


async def run_research_agent(
    role: str, ticker: str, data: Dict[str, Any]
) -> Optional[Dict[str, Any]]:
    """Run one specialist research agent. Returns None on failure."""
    model = RESEARCH_MODELS[role]
    prompt = _build_role_prompt(role, ticker, data)
    response = await query_model(model, [{"role": "user", "content": prompt}])
    if response is None:
        return None
    return {
        "role": role,
        "title": ROLE_TITLES[role],
        "model": model,
        "report": response.get('content', ''),
    }


async def build_dossier(ticker: str, data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Run all research agents in parallel and combine into a dossier.

    Continues with whichever sections succeed (graceful degradation).
    """
    results = await asyncio.gather(
        *[run_research_agent(role, ticker, data) for role in RESEARCH_MODELS]
    )
    sections = [r for r in results if r is not None]

    dossier_text = "\n\n---\n\n".join(
        f"# {s['title']} Report\n\n{s['report']}" for s in sections
    )

    return {
        "sections": sections,
        "data_used": {
            "quote": data["quote"],
            "indicators": data["indicators"],
            "news_count": len(data["news"]),
        },
        "dossier_text": dossier_text,
    }
