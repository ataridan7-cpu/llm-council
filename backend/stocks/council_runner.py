"""Stock-adapted 3-stage council runner.

The chat council in backend.council hardcodes its models and Q&A prompts,
so this module implements its own stages while reusing the genuinely
generic pieces: openrouter.query_model(s), parse_ranking_from_text, and
calculate_aggregate_rankings.
"""

import argparse
import asyncio
import json
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from ..council import parse_ranking_from_text, calculate_aggregate_rankings
from ..openrouter import query_model, query_models_parallel
from . import store
from .config import (
    ANALYST_MODELS,
    STOCK_CHAIRMAN_MODEL,
    CHEAP_MODEL,
    DRY_RUN_MODELS,
    DRY_RUN_TICKERS,
    TICKERS,
    USE_ONLINE_SEARCH,
    STAGE_TIMEOUT,
    MAX_WEIGHT_PER_NAME,
    MAX_GROSS,
)
from .data import get_prices, build_snapshot, build_live_extras, snap_to_trading_day
from .prompts import (
    build_stage1_prompt,
    build_stage2_prompt,
    build_stage3_prompt,
    build_rescue_prompt,
)
from .schemas import CouncilRun, StockVerdict, PortfolioTarget


# ---------------------------------------------------------------------------
# Verdict parsing ladder: fenced JSON -> bracket scan -> cheap-model rescue
# ---------------------------------------------------------------------------

def extract_json_candidates(text: str) -> List[str]:
    """JSON candidate strings, most promising first."""
    candidates: List[str] = []
    # Fenced blocks, last one first (the contract puts the JSON last)
    fenced = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    candidates.extend(reversed([f.strip() for f in fenced if f.strip()]))
    # Outermost brace scan from the last closing brace backwards
    last_close = text.rfind("}")
    if last_close != -1:
        depth = 0
        for i in range(last_close, -1, -1):
            if text[i] == "}":
                depth += 1
            elif text[i] == "{":
                depth -= 1
                if depth == 0:
                    candidates.append(text[i : last_close + 1])
                    break
    return candidates


def parse_verdicts_text(text: str) -> Optional[List[Dict[str, Any]]]:
    """Lenient extraction of a verdicts list from raw chairman output."""
    for candidate in extract_json_candidates(text):
        try:
            data = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(data, dict) and isinstance(data.get("verdicts"), list):
            items = data["verdicts"]
        elif isinstance(data, list):
            items = data
        else:
            continue
        verdicts = [v for v in items if isinstance(v, dict) and v.get("ticker")]
        if verdicts:
            return verdicts
    return None


async def rescue_parse(raw_text: str, tickers: List[str]) -> Optional[List[Dict[str, Any]]]:
    """Cheap-model rescue: re-extract verdicts as strict JSON."""
    response = await query_model(
        CHEAP_MODEL,
        [{"role": "user", "content": build_rescue_prompt(raw_text, tickers)}],
        timeout=60.0,
        extra_payload={"response_format": {"type": "json_object"}},
    )
    if response and response.get("content"):
        return parse_verdicts_text(response["content"])
    return None


_STANCE_ALIASES = {
    "LONG": "LONG", "BUY": "LONG", "BULLISH": "LONG", "OVERWEIGHT": "LONG",
    "SHORT": "SHORT", "SELL": "SHORT", "BEARISH": "SHORT", "UNDERWEIGHT": "SHORT",
    "FLAT": "FLAT", "HOLD": "FLAT", "NEUTRAL": "FLAT", "NONE": "FLAT",
}


def normalize_verdicts(
    raw_verdicts: List[Dict[str, Any]], tickers: List[str]
) -> Tuple[List[StockVerdict], PortfolioTarget]:
    """Coerce raw verdicts into valid, constraint-satisfying positions.

    Always applied, so the portfolio engine never sees invalid weights:
    clamp |w| per name, scale if gross > 1, make sign follow stance (the
    stance is trusted over the sign), fill missing tickers with FLAT.
    """
    by_ticker = {}
    for v in raw_verdicts:
        t = str(v.get("ticker", "")).upper().strip()
        if t:
            by_ticker[t] = v

    verdicts: List[StockVerdict] = []
    for ticker in tickers:
        raw = by_ticker.get(ticker)
        if raw is None:
            verdicts.append(StockVerdict(
                ticker=ticker, stance="FLAT", conviction=5, target_weight=0.0,
                rationale="No verdict returned by the chairman; defaulted to FLAT.",
            ))
            continue

        stance = _STANCE_ALIASES.get(str(raw.get("stance", "")).upper().strip(), "FLAT")
        try:
            weight = float(raw.get("target_weight", 0) or 0)
        except (TypeError, ValueError):
            weight = 0.0
        try:
            conviction = max(1, min(10, round(float(raw.get("conviction", 5)))))
        except (TypeError, ValueError):
            conviction = 5

        if stance == "FLAT":
            weight = 0.0
        elif stance == "LONG":
            weight = abs(weight)
        else:
            weight = -abs(weight)
        weight = max(-MAX_WEIGHT_PER_NAME, min(MAX_WEIGHT_PER_NAME, weight))

        verdicts.append(StockVerdict(
            ticker=ticker,
            stance=stance,
            conviction=conviction,
            target_weight=weight,
            rationale=str(raw.get("rationale", "") or "")[:500],
        ))

    gross = sum(abs(v.target_weight) for v in verdicts)
    if gross > MAX_GROSS:
        scale = MAX_GROSS / gross
        for v in verdicts:
            v.target_weight *= scale
        gross = MAX_GROSS
    for v in verdicts:
        v.target_weight = round(v.target_weight, 4)
    gross = round(sum(abs(v.target_weight) for v in verdicts), 4)

    target = PortfolioTarget(
        weights={v.ticker: v.target_weight for v in verdicts},
        cash=round(max(0.0, 1.0 - gross), 4),
        gross=gross,
    )
    return verdicts, target


# ---------------------------------------------------------------------------
# Stages
# ---------------------------------------------------------------------------

async def _query_analysts(
    models: List[str], prompt: str, online: bool
) -> List[Dict[str, Any]]:
    """Stage-1 queries; with web search enabled, retry once without the
    ':online' suffix if a model fails."""
    messages = [{"role": "user", "content": prompt}]
    if online:
        async def query_with_fallback(model: str):
            response = await query_model(f"{model}:online", messages, timeout=STAGE_TIMEOUT)
            if response is None:
                response = await query_model(model, messages, timeout=STAGE_TIMEOUT)
            return model, response
        pairs = await asyncio.gather(*[query_with_fallback(m) for m in models])
        responses = dict(pairs)
    else:
        responses = await query_models_parallel(models, messages, timeout=STAGE_TIMEOUT)

    return [
        {"model": model, "response": r.get("content", "")}
        for model, r in responses.items()
        if r is not None and r.get("content")
    ]


def _unique_run_id(kind: str, as_of: str) -> str:
    base = f"{kind}-{as_of}"
    run_id, n = base, 2
    while store.load_run(run_id) is not None:
        run_id = f"{base}-{n}"
        n += 1
    return run_id


async def run_stock_council(
    as_of: Optional[date] = None,
    kind: str = "live",
    tickers: Optional[List[str]] = None,
    analysts: Optional[List[str]] = None,
    chairman: Optional[str] = None,
    prices=None,
    on_created=None,
) -> CouncilRun:
    """Run the full 3-stage stock council and persist after every stage so
    progress is pollable and failed runs stay diagnosable.

    on_created: optional async callback invoked with the run_id as soon as
    the run record exists (lets the API return 202 with the id immediately).
    """
    if kind == "dry_run":
        tickers = tickers or DRY_RUN_TICKERS
        analysts = analysts or DRY_RUN_MODELS
        chairman = chairman or CHEAP_MODEL
    else:
        tickers = tickers or TICKERS
        analysts = analysts or ANALYST_MODELS
        chairman = chairman or STOCK_CHAIRMAN_MODEL

    if prices is None:
        # Network fetch is sync; keep it off the event loop
        prices = await asyncio.to_thread(get_prices)
    as_of = as_of or date.today()
    as_of_ts = snap_to_trading_day(as_of, prices.index)
    as_of_str = str(as_of_ts.date())

    use_online = USE_ONLINE_SEARCH and kind == "live"
    run = CouncilRun(
        run_id=_unique_run_id(kind, as_of_str),
        kind=kind,
        as_of=as_of_str,
        created_at=datetime.now(timezone.utc).isoformat(),
        status="running",
        progress={"stage": "stage1"},
        models={"analysts": analysts, "chairman": chairman, "online_search": use_online},
        tickers=tickers,
    )
    store.save_run(run)
    if on_created is not None:
        await on_created(run.run_id)

    try:
        # --- Stage 1: analyst memos (one cross-sectional prompt per model)
        snapshots = [build_snapshot(t, as_of_ts.date(), prices) for t in tickers]
        live_extras = (
            await asyncio.gather(*[asyncio.to_thread(build_live_extras, t) for t in tickers])
            if kind == "live"
            else None
        )
        live_extras = list(live_extras) if live_extras else None
        run.data_summary = {
            "snapshots": snapshots,
            "live_extras_included": kind == "live",
            "point_in_time_only": kind in ("historical", "dry_run"),
        }
        stage1_prompt = build_stage1_prompt(as_of_str, kind, snapshots, live_extras)
        run.stage1 = await _query_analysts(analysts, stage1_prompt, use_online)
        if not run.stage1:
            raise RuntimeError("All analyst models failed in stage 1")
        run.progress = {"stage": "stage2"}
        store.save_run(run)

        # --- Stage 2: anonymized peer ranking (same contract as the chat council)
        labels = [chr(65 + i) for i in range(len(run.stage1))]
        run.label_to_model = {
            f"Response {label}": r["model"] for label, r in zip(labels, run.stage1)
        }
        responses_text = "\n\n".join(
            f"Response {label}:\n{r['response']}"
            for label, r in zip(labels, run.stage1)
        )
        stage2_prompt = build_stage2_prompt(as_of_str, responses_text)
        ranking_responses = await query_models_parallel(
            analysts, [{"role": "user", "content": stage2_prompt}], timeout=STAGE_TIMEOUT
        )
        run.stage2 = [
            {
                "model": model,
                "ranking": r["content"],
                "parsed_ranking": parse_ranking_from_text(r["content"]),
            }
            for model, r in ranking_responses.items()
            if r is not None and r.get("content")
        ]
        run.aggregate_rankings = calculate_aggregate_rankings(run.stage2, run.label_to_model)
        run.progress = {"stage": "stage3"}
        store.save_run(run)

        # --- Stage 3: chairman synthesis -> machine-readable verdicts
        stage1_text = "\n\n".join(
            f"Analyst: {r['model']}\nMemo:\n{r['response']}" for r in run.stage1
        )
        stage2_text = "\n\n".join(
            f"Evaluator: {r['model']}\n{r['ranking']}" for r in run.stage2
        )
        aggregate_text = json.dumps(run.aggregate_rankings, indent=2)
        stage3_prompt = build_stage3_prompt(
            as_of_str, kind, tickers, stage1_text, stage2_text, aggregate_text
        )
        chairman_response = await query_model(
            chairman, [{"role": "user", "content": stage3_prompt}], timeout=STAGE_TIMEOUT
        )
        if chairman_response is None or not chairman_response.get("content"):
            raise RuntimeError(f"Chairman model {chairman} failed in stage 3")
        run.stage3 = {"model": chairman, "response": chairman_response["content"]}
        run.progress = {"stage": "parsing"}
        store.save_run(run)

        # --- Parse + normalize verdicts
        raw_verdicts = parse_verdicts_text(run.stage3["response"])
        if raw_verdicts is None:
            raw_verdicts = await rescue_parse(run.stage3["response"], tickers)
        if raw_verdicts is None:
            raise RuntimeError(
                "Could not parse verdicts from chairman output (raw text preserved)"
            )
        run.verdicts, run.portfolio_target = normalize_verdicts(raw_verdicts, tickers)
        run.status = "complete"
        run.progress = {"stage": "done"}
        store.save_run(run)

    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        store.save_run(run)

    return run


async def run_locked(coro_factory):
    """Serialize council runs behind the global run lock."""
    async with store.RUN_LOCK:
        return await coro_factory()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the stock council once")
    parser.add_argument("--dry-run", action="store_true",
                        help="2 cheap models x 2 tickers (~$0.01) to validate the pipeline")
    parser.add_argument("--as-of", type=str, default=None, help="YYYY-MM-DD")
    parser.add_argument("--kind", type=str, default=None,
                        choices=["live", "historical", "dry_run"])
    args = parser.parse_args()

    kind = "dry_run" if args.dry_run else (args.kind or "live")
    as_of = date.fromisoformat(args.as_of) if args.as_of else None

    run = asyncio.run(run_stock_council(as_of=as_of, kind=kind))
    print(f"Run {run.run_id}: {run.status}")
    if run.status == "complete":
        for v in run.verdicts:
            print(f"  {v.ticker}: {v.stance} conviction={v.conviction} weight={v.target_weight:+.2%}")
        print(f"  cash: {run.portfolio_target.cash:.2%}")
    elif run.error:
        print(f"  error: {run.error}")


if __name__ == "__main__":
    main()
