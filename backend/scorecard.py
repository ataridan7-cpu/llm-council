"""Prediction recording and outcome evaluation."""

import uuid
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import HOLD_BAND
from .market_data import get_close_on_or_after


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

    prediction = {
        "id": str(uuid.uuid4()),
        "ticker": analysis["ticker"],
        "analysis_id": analysis["id"],
        "created_at": created_at,
        "price_at_prediction": (analysis.get("market_snapshot") or {}).get("price"),
        "council_verdict": council_verdict,
        "model_verdicts": model_verdicts,
        "outcomes": {
            "1w": {"due_at": _due_at(created_at, 7), "status": "pending", "actual_price": None, "actual_return": None, "results": {}},
            "1m": {"due_at": _due_at(created_at, 30), "status": "pending", "actual_price": None, "actual_return": None, "results": {}},
            "3m": {"due_at": _due_at(created_at, 90), "status": "pending", "actual_price": None, "actual_return": None, "results": {}},
        },
    }

    storage.save_prediction(prediction)
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

    # direction_hit: did predicted direction match actual movement?
    if abs(ret) <= hold_band:
        actual_direction = "flat"
    elif ret > 0:
        actual_direction = "up"
    else:
        actual_direction = "down"
    direction_hit = direction == actual_direction if direction else None

    # verdict_hit: did the buy/hold/sell call pay off?
    if v == "buy":
        verdict_hit = ret > hold_band
    elif v == "sell":
        verdict_hit = ret < -hold_band
    else:
        verdict_hit = abs(ret) <= hold_band

    # target_in_range: was actual price inside the predicted range?
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
    Idempotent: scan pending prediction timeframes, fetch actual prices,
    score against council + per-model verdicts.
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

            # Fetch actual price
            try:
                close = await get_close_on_or_after(ticker, due_at)
            except Exception as e:
                errors.append(f"{ticker}/{tf}: {e}")
                continue

            days_overdue = (now - due_dt).days
            if close is None:
                if days_overdue > 10:
                    outcome["status"] = "unavailable"
                    changed = True
                else:
                    skipped += 1
                continue

            actual_price = close["close"]
            outcome["actual_price"] = actual_price
            outcome["actual_return"] = round(actual_price / price_at - 1, 4) if price_at else None

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
    """Compute hit-rate leaderboard across all evaluated predictions."""
    from . import storage

    # entity -> timeframe -> list of score dicts
    entity_scores: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))

    for pred_meta in storage.list_predictions():
        pred = storage.get_prediction(pred_meta["id"])
        if pred is None:
            continue

        for tf, outcome in pred.get("outcomes", {}).items():
            if outcome.get("status") != "evaluated":
                continue
            for entity, score in outcome.get("results", {}).items():
                entity_scores[entity][tf].append(score)

    leaderboard = []
    for entity, tf_scores in entity_scores.items():
        row = {"entity": entity, "timeframes": {}}
        total_direction = total_verdict = total_n = 0

        for tf in ("1w", "1m", "3m"):
            scores = tf_scores.get(tf, [])
            n = len(scores)
            if n == 0:
                continue
            dh = [s["direction_hit"] for s in scores if s["direction_hit"] is not None]
            vh = [s["verdict_hit"] for s in scores if s["verdict_hit"] is not None]
            row["timeframes"][tf] = {
                "n": n,
                "direction_hit_rate": round(sum(dh) / len(dh), 3) if dh else None,
                "verdict_hit_rate": round(sum(vh) / len(vh), 3) if vh else None,
            }
            total_direction += sum(dh)
            total_verdict += sum(vh)
            total_n += n

        row["overall"] = {
            "n": total_n,
            "direction_hit_rate": round(total_direction / total_n, 3) if total_n else None,
            "verdict_hit_rate": round(total_verdict / total_n, 3) if total_n else None,
        }
        leaderboard.append(row)

    leaderboard.sort(key=lambda x: -(x["overall"]["verdict_hit_rate"] or 0))
    return {"leaderboard": leaderboard}
