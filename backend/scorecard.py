"""Prediction recording and outcome evaluation with S&P 500 benchmark comparison."""

import asyncio
import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import BENCHMARK_TICKER, HOLD_BAND
from .market_data import get_close_on_or_after, get_quote


def _due_at(created_at: str, days: int) -> str:
    dt = datetime.fromisoformat(created_at[:19])
    return (dt + timedelta(days=days)).isoformat()


def record_prediction(analysis: Dict[str, Any]) -> Dict[str, Any]:
    """Build and persist a prediction record from a fresh analysis."""
    from . import storage

    created_at = analysis["created_at"]
    council_verdict = (analysis.get("stage3") or {}).get("verdict")
    model_verdicts = [
        {"model": r["model"], "verdict": r.get("verdict")}
        for r in (analysis.get("stage1") or [])
    ]

    # Record SPY price at prediction time for benchmark comparison
    spy_price_at = None  # filled async during recording if available

    prediction = {
        "id": str(uuid.uuid4()),
        "ticker": analysis["ticker"],
        "analysis_id": analysis["id"],
        "created_at": created_at,
        "price_at_prediction": (analysis.get("market_snapshot") or {}).get("price"),
        "spy_price_at_prediction": None,  # filled by record_prediction_with_spy
        "council_verdict": council_verdict,
        "model_verdicts": model_verdicts,
        "outcomes": {
            "1w": {
                "due_at": _due_at(created_at, 7),
                "status": "pending",
                "actual_price": None,
                "actual_return": None,
                "spy_return": None,
                "alpha": None,
                "results": {},
            },
            "1m": {
                "due_at": _due_at(created_at, 30),
                "status": "pending",
                "actual_price": None,
                "actual_return": None,
                "spy_return": None,
                "alpha": None,
                "results": {},
            },
            "3m": {
                "due_at": _due_at(created_at, 90),
                "status": "pending",
                "actual_price": None,
                "actual_return": None,
                "spy_return": None,
                "alpha": None,
                "results": {},
            },
        },
    }

    storage.save_prediction(prediction)
    return prediction


async def _fetch_spy_price_at_prediction(created_at: str) -> Optional[float]:
    """Get SPY price at prediction creation time — uses live quote, falls back to next close."""
    try:
        quote = await get_quote(BENCHMARK_TICKER)
        if quote and quote.get("price"):
            return quote["price"]
        # Fallback: first close on or after the prediction date
        close = await get_close_on_or_after(BENCHMARK_TICKER, created_at)
        return close["close"] if close else None
    except Exception:
        return None


async def enrich_prediction_with_spy(prediction: Dict[str, Any]) -> Dict[str, Any]:
    """
    Fetch SPY price at prediction time and store it. Called right after
    record_prediction so we have the baseline for future alpha calculation.
    """
    from . import storage

    if prediction.get("spy_price_at_prediction") is not None:
        return prediction

    spy_price = await _fetch_spy_price_at_prediction(prediction["created_at"])
    if spy_price:
        prediction["spy_price_at_prediction"] = spy_price
        storage.update_prediction(prediction)
    return prediction


def score_one(
    verdict: Optional[Dict[str, Any]],
    price_at: float,
    actual_price: float,
    timeframe: str,
    hold_band: float = HOLD_BAND,
) -> Dict[str, Any]:
    """Score a single verdict against an actual price."""
    ret = actual_price / price_at - 1 if price_at else None

    if verdict is None or ret is None:
        return {"direction_hit": None, "verdict_hit": None, "target_in_range": None, "return": ret}

    v = verdict.get("verdict")
    targets = (verdict.get("price_targets") or {}).get(timeframe, {})
    direction = targets.get("direction")

    if abs(ret) <= hold_band:
        actual_direction = "flat"
    elif ret > 0:
        actual_direction = "up"
    else:
        actual_direction = "down"
    direction_hit = direction == actual_direction if direction else None

    if v == "buy":
        verdict_hit = ret > hold_band
    elif v == "sell":
        verdict_hit = ret < -hold_band
    else:
        verdict_hit = abs(ret) <= hold_band

    low = targets.get("low")
    high = targets.get("high")
    target_in_range = (low <= actual_price <= high) if (low is not None and high is not None) else None

    return {
        "direction_hit": direction_hit,
        "verdict_hit": verdict_hit,
        "target_in_range": target_in_range,
        "return": round(ret, 4),
    }


async def evaluate_due_predictions() -> Dict[str, Any]:
    """
    Idempotent: scan pending prediction timeframes, fetch actual prices and
    SPY benchmark returns, score against council + per-model verdicts.
    """
    from . import storage

    evaluated = 0
    skipped = 0
    errors = []

    for pred_meta in storage.list_predictions(status="pending"):
        pred = storage.get_prediction(pred_meta["id"])
        if pred is None:
            continue

        ticker = pred["ticker"]
        price_at = pred.get("price_at_prediction")
        if not price_at:
            continue

        # Ensure SPY baseline is recorded
        if pred.get("spy_price_at_prediction") is None:
            pred = await enrich_prediction_with_spy(pred)

        spy_price_at = pred.get("spy_price_at_prediction")

        changed = False
        for tf, outcome in pred["outcomes"].items():
            if outcome["status"] != "pending":
                continue

            due_at = outcome.get("due_at")
            if not due_at:
                continue

            due_dt = datetime.fromisoformat(due_at[:19])
            now = datetime.utcnow()

            if now < due_dt:
                skipped += 1
                continue

            # Fetch stock and SPY prices concurrently
            try:
                stock_close, spy_close = await asyncio.gather(
                    get_close_on_or_after(ticker, due_at),
                    get_close_on_or_after(BENCHMARK_TICKER, due_at),
                )
            except Exception as e:
                errors.append(f"{ticker}/{tf}: {e}")
                continue

            days_overdue = (now - due_dt).days
            if stock_close is None:
                if days_overdue > 10:
                    outcome["status"] = "unavailable"
                    changed = True
                else:
                    skipped += 1
                continue

            actual_price = stock_close["close"]
            actual_return = round(actual_price / price_at - 1, 4) if price_at else None

            # S&P 500 benchmark return over same window
            spy_return = None
            alpha = None
            if spy_close and spy_price_at:
                spy_return = round(spy_close["close"] / spy_price_at - 1, 4)
                if actual_return is not None:
                    alpha = round(actual_return - spy_return, 4)

            outcome["actual_price"] = actual_price
            outcome["actual_return"] = actual_return
            outcome["spy_return"] = spy_return
            outcome["alpha"] = alpha  # stock return minus S&P 500 return

            # Score council
            council_score = score_one(pred.get("council_verdict"), price_at, actual_price, tf)
            results = {"council": council_score}

            # Score each model
            for mv in (pred.get("model_verdicts") or []):
                model_score = score_one(mv.get("verdict"), price_at, actual_price, tf)
                results[mv["model"]] = model_score

            outcome["results"] = results
            outcome["status"] = "evaluated"
            evaluated += 1
            changed = True

        if changed:
            storage.update_prediction(pred)

    return {"evaluated": evaluated, "skipped": skipped, "errors": errors}


def compute_leaderboard() -> Dict[str, Any]:
    """
    Compute hit-rate leaderboard across all evaluated predictions,
    including average alpha vs S&P 500.
    """
    from . import storage

    # entity -> timeframe -> list of score dicts
    entity_scores: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))
    # store alpha per timeframe (from outcome, not per entity)
    tf_alphas: Dict[str, List[float]] = defaultdict(list)
    # per prediction's council verdict, track alpha
    council_alphas: Dict[str, List[float]] = defaultdict(list)

    for pred_meta in storage.list_predictions():
        pred = storage.get_prediction(pred_meta["id"])
        if pred is None:
            continue

        for tf, outcome in pred.get("outcomes", {}).items():
            if outcome.get("status") != "evaluated":
                continue

            alpha = outcome.get("alpha")
            council_verdict = (pred.get("council_verdict") or {}).get("verdict")

            # Track alpha per timeframe for council calls only
            if alpha is not None and council_verdict:
                council_alphas[tf].append(alpha)

            for entity, score in outcome.get("results", {}).items():
                entity_scores[entity][tf].append(score)

    leaderboard = []
    for entity, tf_scores in entity_scores.items():
        row = {"entity": entity, "timeframes": {}}
        total_direction = total_verdict = total_n = 0
        all_dh = []
        all_vh = []

        for tf in ("1w", "1m", "3m"):
            scores = tf_scores.get(tf, [])
            n = len(scores)
            if n == 0:
                continue
            dh = [s["direction_hit"] for s in scores if s["direction_hit"] is not None]
            vh = [s["verdict_hit"] for s in scores if s["verdict_hit"] is not None]
            all_dh.extend(dh)
            all_vh.extend(vh)

            tf_row = {
                "n": n,
                "direction_hit_rate": round(sum(dh) / len(dh), 3) if dh else None,
                "verdict_hit_rate": round(sum(vh) / len(vh), 3) if vh else None,
            }

            # Add alpha (only on council entity — the strategy return vs SPY)
            if entity == "council" and council_alphas.get(tf):
                alphas = council_alphas[tf]
                tf_row["avg_alpha"] = round(sum(alphas) / len(alphas), 4)
                tf_row["beat_spy_rate"] = round(sum(1 for a in alphas if a > 0) / len(alphas), 3)
            else:
                tf_row["avg_alpha"] = None
                tf_row["beat_spy_rate"] = None

            row["timeframes"][tf] = tf_row
            total_n += n

        row["overall"] = {
            "n": total_n,
            "direction_hit_rate": round(sum(all_dh) / len(all_dh), 3) if all_dh else None,
            "verdict_hit_rate": round(sum(all_vh) / len(all_vh), 3) if all_vh else None,
        }

        # Overall alpha for council
        if entity == "council":
            all_alphas = [a for tf_list in council_alphas.values() for a in tf_list]
            if all_alphas:
                row["overall"]["avg_alpha"] = round(sum(all_alphas) / len(all_alphas), 4)
                row["overall"]["beat_spy_rate"] = round(
                    sum(1 for a in all_alphas if a > 0) / len(all_alphas), 3
                )

        leaderboard.append(row)

    leaderboard.sort(key=lambda x: -(x["overall"]["verdict_hit_rate"] or 0))
    return {"leaderboard": leaderboard}


def compute_portfolio_summary() -> Dict[str, Any]:
    """
    Portfolio-level summary: treat every council verdict as an equal-weight
    position and compute aggregate returns + alpha vs S&P 500.
    Includes a per-ticker breakdown.
    """
    from . import storage
    from .config import TRACKED_TICKERS

    per_ticker: Dict[str, Dict[str, Any]] = {t: {
        "ticker": t,
        "n_evaluated": 0,
        "n_pending": 0,
        "n_total": 0,
        "verdicts": {"buy": 0, "hold": 0, "sell": 0},
        "timeframes": {},
        "alphas": [],
    } for t in TRACKED_TICKERS}

    all_alphas: List[float] = []
    all_returns: List[float] = []
    all_verdict_hits: List[bool] = []

    for pred_meta in storage.list_predictions():
        pred = storage.get_prediction(pred_meta["id"])
        if pred is None:
            continue

        ticker = pred.get("ticker")
        if ticker not in per_ticker:
            continue

        bucket = per_ticker[ticker]
        bucket["n_total"] += 1

        council_verdict_obj = pred.get("council_verdict")
        cv = (council_verdict_obj or {}).get("verdict")
        if cv in bucket["verdicts"]:
            bucket["verdicts"][cv] += 1

        any_evaluated = False
        for tf, outcome in pred.get("outcomes", {}).items():
            if outcome.get("status") != "evaluated":
                continue
            any_evaluated = True
            alpha = outcome.get("alpha")
            ret = outcome.get("actual_return")
            score = score_one(council_verdict_obj, pred.get("price_at_prediction", 0),
                              outcome.get("actual_price", 0), tf)

            if tf not in bucket["timeframes"]:
                bucket["timeframes"][tf] = {"alphas": [], "returns": [], "verdict_hits": []}

            if alpha is not None:
                bucket["timeframes"][tf]["alphas"].append(alpha)
                all_alphas.append(alpha)
            if ret is not None:
                bucket["timeframes"][tf]["returns"].append(ret)
                all_returns.append(ret)
            if score.get("verdict_hit") is not None:
                bucket["timeframes"][tf]["verdict_hits"].append(score["verdict_hit"])
                all_verdict_hits.append(score["verdict_hit"])
                if score["verdict_hit"]:
                    bucket["alphas"].append(alpha or 0.0)

        if any_evaluated:
            bucket["n_evaluated"] += 1
        else:
            bucket["n_pending"] += 1

    # Summarise per-ticker timeframes
    ticker_rows = []
    for ticker, bucket in per_ticker.items():
        tf_summary = {}
        for tf, vals in bucket["timeframes"].items():
            alphas = vals["alphas"]
            rets = vals["returns"]
            vhits = vals["verdict_hits"]
            tf_summary[tf] = {
                "avg_alpha": round(sum(alphas) / len(alphas), 4) if alphas else None,
                "avg_return": round(sum(rets) / len(rets), 4) if rets else None,
                "verdict_hit_rate": round(sum(vhits) / len(vhits), 3) if vhits else None,
                "n": len(alphas) or len(rets),
            }

        ticker_rows.append({
            "ticker": ticker,
            "n_total": bucket["n_total"],
            "n_evaluated": bucket["n_evaluated"],
            "n_pending": bucket["n_pending"],
            "verdicts": bucket["verdicts"],
            "timeframes": tf_summary,
        })

    # Portfolio-wide aggregates
    total_n = len(all_alphas)
    portfolio = {
        "n_evaluated": total_n,
        "avg_alpha": round(sum(all_alphas) / total_n, 4) if all_alphas else None,
        "beat_spy_rate": round(sum(1 for a in all_alphas if a > 0) / total_n, 3) if all_alphas else None,
        "avg_return": round(sum(all_returns) / len(all_returns), 4) if all_returns else None,
        "verdict_hit_rate": round(sum(all_verdict_hits) / len(all_verdict_hits), 3) if all_verdict_hits else None,
    }

    return {"portfolio": portfolio, "tickers": ticker_rows}
