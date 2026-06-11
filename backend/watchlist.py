"""Live quote refresh and alert generation for the fixed tracked universe."""

import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import TRACKED_TICKERS, HOLD_BAND, WATCHLIST_QUICK_SIGNAL, REPAIR_MODEL
from .market_data import get_quote
from . import storage


async def _quick_signal(ticker: str, quote: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """
    One cheap-model call per ticker → {signal: bullish/neutral/bearish, note: str}.
    Only called when WATCHLIST_QUICK_SIGNAL=true.
    """
    from .openrouter import query_model

    if not quote:
        return None

    price = quote.get("price", "N/A")
    prev_close = quote.get("prev_close")
    change_pct = ""
    if price and prev_close:
        pct = (price / prev_close - 1) * 100
        change_pct = f" ({'+' if pct >= 0 else ''}{pct:.2f}% today)"

    prompt = (
        f"You are a brief market analyst. {ticker} is trading at ${price}{change_pct}.\n"
        "In exactly 2 sentences, give a quick market sentiment signal.\n"
        "End your response with JSON on a new line: "
        '{"signal": "bullish" | "neutral" | "bearish", "note": "<one sentence reason>"}'
    )
    try:
        result = await query_model(REPAIR_MODEL, [{"role": "user", "content": prompt}])
        if not result:
            return None
        content = result.get("content", "")
        # Extract JSON from the response
        import json, re
        m = re.search(r'\{[^}]+\}', content, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            if data.get("signal") in ("bullish", "neutral", "bearish"):
                return {"signal": data["signal"], "note": data.get("note", "")}
    except Exception:
        pass
    return None


async def refresh_watchlist() -> List[Dict[str, Any]]:
    """
    Fetch live quotes for all tracked tickers and compute alerts.
    When WATCHLIST_QUICK_SIGNAL=true, also runs one cheap LLM call per ticker.
    """
    quotes = await asyncio.gather(*[get_quote(t) for t in TRACKED_TICKERS])

    if WATCHLIST_QUICK_SIGNAL:
        signals = await asyncio.gather(*[
            _quick_signal(ticker, quote)
            for ticker, quote in zip(TRACKED_TICKERS, quotes)
        ])
    else:
        signals = [None] * len(TRACKED_TICKERS)

    rows = []
    for ticker, quote, signal in zip(TRACKED_TICKERS, quotes, signals):
        row = _build_row(ticker, quote)
        row["quick_signal"] = signal
        rows.append(row)
    return rows


def _build_row(ticker: str, quote: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    analyses = storage.list_analyses(ticker=ticker)
    latest_analysis = analyses[0] if analyses else None
    predictions = storage.list_predictions(ticker=ticker)

    price = (quote or {}).get("price")
    prev_close = (quote or {}).get("prev_close")
    day_change_pct = None
    if price and prev_close:
        day_change_pct = round((price / prev_close - 1) * 100, 2)

    verdict = latest_analysis.get("verdict") if latest_analysis else None
    confidence = latest_analysis.get("confidence") if latest_analysis else None
    created_at = latest_analysis.get("created_at") if latest_analysis else None
    verdict_age_days = None
    if created_at:
        try:
            age = datetime.utcnow() - datetime.fromisoformat(created_at[:19])
            verdict_age_days = age.days
        except ValueError:
            pass

    alerts = _compute_alerts(
        ticker, price, day_change_pct, latest_analysis, predictions, verdict_age_days
    )

    return {
        "ticker": ticker,
        "name": (quote or {}).get("name", ticker),
        "price": price,
        "prev_close": prev_close,
        "day_change_pct": day_change_pct,
        "currency": (quote or {}).get("currency", "USD"),
        "latest_verdict": verdict,
        "latest_confidence": confidence,
        "verdict_age_days": verdict_age_days,
        "alerts": alerts,
        "stale": (quote or {}).get("stale", False),
    }


def _compute_alerts(
    ticker: str,
    price: Optional[float],
    day_change_pct: Optional[float],
    latest_analysis: Optional[Dict],
    predictions: List[Dict],
    verdict_age_days: Optional[int],
) -> List[Dict[str, str]]:
    alerts = []

    # Big day move
    if day_change_pct is not None and abs(day_change_pct) >= 5:
        direction = "up" if day_change_pct > 0 else "down"
        alerts.append({
            "type": "big_move",
            "message": f"Large day move: {'+' if day_change_pct > 0 else ''}{day_change_pct:.1f}% ({direction})",
        })

    # Stale analysis (no analysis in 30d)
    if latest_analysis is None:
        alerts.append({"type": "no_analysis", "message": "No analysis run yet"})
    elif verdict_age_days is not None and verdict_age_days >= 30:
        alerts.append({
            "type": "stale_analysis",
            "message": f"Analysis is {verdict_age_days} days old — consider re-running",
        })

    # Price entered/exited the council's 1-month target range
    if price and latest_analysis:
        # We'd need the full analysis to get targets; check from predictions
        for pred in predictions[:1]:
            council_verdict = storage.get_prediction(pred["id"]) if pred.get("id") else None
            if council_verdict:
                t1m = (council_verdict.get("council_verdict") or {}).get("price_targets", {}).get("1m", {})
                low, high = t1m.get("low"), t1m.get("high")
                if low and high:
                    if low <= price <= high:
                        alerts.append({
                            "type": "in_target",
                            "message": f"Price ${price:.2f} is inside the council's 1-month target range (${low:.2f}–${high:.2f})",
                        })

    # Prediction timeframes coming due
    now = datetime.utcnow()
    for pred_meta in predictions[:3]:
        pred = storage.get_prediction(pred_meta["id"]) if pred_meta.get("id") else None
        if not pred:
            continue
        for tf, outcome in pred.get("outcomes", {}).items():
            if outcome.get("status") != "pending":
                continue
            due_at = outcome.get("due_at")
            if not due_at:
                continue
            try:
                due_dt = datetime.fromisoformat(due_at[:19])
                days_until = (due_dt - now).days
                if 0 <= days_until <= 2:
                    alerts.append({
                        "type": "prediction_due",
                        "message": f"{tf} prediction due {'today' if days_until == 0 else f'in {days_until}d'} — click Evaluate Now on Scorecard",
                    })
            except ValueError:
                pass

    return alerts
