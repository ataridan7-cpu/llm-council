"""Stock analysis pipeline: Stage 0 (research) + council Stages 1-3."""

import asyncio
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .config import CHAIRMAN_MODEL, COUNCIL_MODELS
from .council import (
    calculate_aggregate_rankings,
    stage2_collect_rankings,
)
from .openrouter import query_model, query_models_parallel
from .research import build_dossier, gather_market_data
from .verdict import VERDICT_JSON_INSTRUCTIONS, StockVerdict, parse_or_repair_verdict


def build_analysis_question(ticker: str, quote: Dict[str, Any]) -> str:
    name = quote.get("name", ticker)
    price = quote.get("price")
    currency = quote.get("currency", "USD")
    return (
        f"Investment analysis request for {name} ({ticker}) — "
        f"current price {price} {currency}. "
        "Based on the research dossier provided, what is the investment case? "
        "Provide a buy/hold/sell recommendation with 1-week, 1-month, and 3-month price targets."
    )


def _build_stage1_prompt(
    ticker: str, quote: Dict[str, Any], dossier_text: str
) -> str:
    name = quote.get("name", ticker)
    price = quote.get("price")
    currency = quote.get("currency", "USD")
    return f"""You are a senior portfolio manager on an investment council analyzing {name} ({ticker}).
Current price: {price} {currency}

A team of specialist analysts has prepared the following research dossier:

{dossier_text}

Your task:
1. Evaluate the investment case based on the dossier — cover the bull case, bear case, key risks, and your overall thesis.
2. State your recommendation (buy / hold / sell) with a confidence level (0-100).
3. Provide absolute price targets (in {currency}) for 1 week, 1 month, and 3 months — anchored to the current price of {price}.

{VERDICT_JSON_INSTRUCTIONS}"""


def _build_stage3_prompt(
    ticker: str,
    quote: Dict[str, Any],
    dossier_text: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
) -> str:
    name = quote.get("name", ticker)
    price = quote.get("price")
    currency = quote.get("currency", "USD")

    stage1_text = "\n\n".join(
        f"Council Member ({r['model']}):\n{r['response']}"
        for r in stage1_results
    )
    stage2_text = "\n\n".join(
        f"Evaluator ({r['model']}):\n{r['ranking']}"
        for r in stage2_results
    )

    return f"""You are the Chairman of an Investment Council synthesizing the final report for {name} ({ticker}).
Current price: {price} {currency}

RESEARCH DOSSIER (prepared by specialist analysts):
{dossier_text}

STAGE 1 — Individual Council Verdicts:
{stage1_text}

STAGE 2 — Peer Evaluations:
{stage2_text}

Write a comprehensive investment report with the following sections (use these exact headings):
## Executive Summary
## Verdict & Confidence
## Price Outlook (1w / 1m / 3m table with low / base / high scenarios)
## Bull Case
## Bear Case
## Key Risks
## Disclaimer
*This report is for research and educational purposes only. It is NOT financial advice. Past model predictions do not guarantee future accuracy. Always do your own research.*

After the report, provide your synthesized final verdict.

{VERDICT_JSON_INSTRUCTIONS}"""


async def stage1_collect_verdicts(
    ticker: str, quote: Dict[str, Any], dossier_text: str
) -> List[Dict[str, Any]]:
    prompt = _build_stage1_prompt(ticker, quote, dossier_text)
    messages = [{"role": "user", "content": prompt}]
    responses = await query_models_parallel(COUNCIL_MODELS, messages)

    results = []
    verdict_tasks = []
    ordered_models = []
    ordered_responses = []

    for model, response in responses.items():
        if response is not None:
            content = response.get('content', '')
            ordered_models.append(model)
            ordered_responses.append(content)
            verdict_tasks.append(parse_or_repair_verdict(content))

    verdicts = await asyncio.gather(*verdict_tasks)

    for model, content, verdict in zip(ordered_models, ordered_responses, verdicts):
        results.append({
            "model": model,
            "response": content,
            "verdict": verdict.model_dump() if verdict else None,
        })

    return results


async def stage3_chairman_report(
    ticker: str,
    quote: Dict[str, Any],
    dossier_text: str,
    stage1_results: List[Dict[str, Any]],
    stage2_results: List[Dict[str, Any]],
) -> Dict[str, Any]:
    prompt = _build_stage3_prompt(ticker, quote, dossier_text, stage1_results, stage2_results)
    messages = [{"role": "user", "content": prompt}]
    response = await query_model(CHAIRMAN_MODEL, messages)

    if response is None:
        return {
            "model": CHAIRMAN_MODEL,
            "response": "Error: Chairman model failed to respond.",
            "verdict": None,
        }

    content = response.get('content', '')
    verdict = await parse_or_repair_verdict(content)
    return {
        "model": CHAIRMAN_MODEL,
        "response": content,
        "verdict": verdict.model_dump() if verdict else None,
    }


async def run_stock_analysis(ticker: str) -> Dict[str, Any]:
    """
    Full pipeline: data fetch → Stage 0 dossier → council Stages 1-3 → persist.

    Returns the complete analysis dict (also saved to disk).
    """
    from . import storage
    from .scorecard import record_prediction, enrich_prediction_with_spy

    ticker = ticker.strip().upper()
    analysis_id = str(uuid.uuid4())

    # Fetch market data (raises ValueError on bad ticker)
    data = await gather_market_data(ticker)
    quote = data["quote"]

    # Stage 0: build research dossier
    dossier = await build_dossier(ticker, data)
    dossier_text = dossier["dossier_text"]

    question = build_analysis_question(ticker, quote)

    # Stage 1: council verdicts
    stage1_results = await stage1_collect_verdicts(ticker, quote, dossier_text)

    if not stage1_results:
        raise RuntimeError("All council models failed to respond.")

    # Stage 2: anonymized peer ranking (reuse existing council machinery verbatim)
    stage2_results, label_to_model = await stage2_collect_rankings(question, stage1_results)
    aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)

    # Stage 3: chairman synthesis
    stage3_result = await stage3_chairman_report(
        ticker, quote, dossier_text, stage1_results, stage2_results
    )

    metadata = {
        "label_to_model": label_to_model,
        "aggregate_rankings": aggregate_rankings,
    }

    analysis = {
        "id": analysis_id,
        "ticker": ticker,
        "created_at": datetime.utcnow().isoformat(),
        "question": question,
        "market_snapshot": quote,
        "dossier": dossier,
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata,
        "prediction_id": None,
    }

    # Persist analysis
    storage.save_analysis(analysis)

    # Record prediction + fetch SPY baseline price for benchmark comparison
    prediction = record_prediction(analysis)
    await enrich_prediction_with_spy(prediction)
    analysis["prediction_id"] = prediction["id"]
    storage.save_analysis(analysis)

    return analysis
