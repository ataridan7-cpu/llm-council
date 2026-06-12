"""Verdict parsing ladder + normalization + a fully-mocked end-to-end run."""

import json
from datetime import date

import pytest

from .. import council_runner
from ..council_runner import (
    parse_verdicts_text,
    normalize_verdicts,
    run_stock_council,
)

CLEAN_JSON = json.dumps({
    "verdicts": [
        {"ticker": "NVDA", "stance": "LONG", "conviction": 8, "target_weight": 0.2, "rationale": "x"},
        {"ticker": "TSLA", "stance": "SHORT", "conviction": 6, "target_weight": -0.1, "rationale": "y"},
    ]
})


def test_parse_clean_fenced_json():
    text = f"Some synthesis prose.\n\n```json\n{CLEAN_JSON}\n```"
    verdicts = parse_verdicts_text(text)
    assert {v["ticker"] for v in verdicts} == {"NVDA", "TSLA"}


def test_parse_json_buried_in_prose_without_fence():
    text = f"The council concluded as follows: {CLEAN_JSON} -- end of report."
    verdicts = parse_verdicts_text(text)
    assert verdicts is not None
    assert verdicts[0]["ticker"] == "NVDA"


def test_parse_picks_last_fenced_block():
    decoy = '```json\n{"verdicts": [{"ticker": "OLD", "stance": "LONG"}]}\n```'
    text = f"{decoy}\nRevised:\n```json\n{CLEAN_JSON}\n```"
    verdicts = parse_verdicts_text(text)
    assert {v["ticker"] for v in verdicts} == {"NVDA", "TSLA"}


def test_parse_malformed_returns_none():
    assert parse_verdicts_text("no json here at all") is None
    assert parse_verdicts_text('```json\n{"verdicts": [{{bad}}]\n```') is None


def test_normalize_trusts_stance_over_sign():
    raw = [
        {"ticker": "NVDA", "stance": "SHORT", "conviction": 7, "target_weight": 0.2},
        {"ticker": "TSLA", "stance": "LONG", "conviction": 7, "target_weight": -0.15},
        {"ticker": "AAPL", "stance": "FLAT", "conviction": 5, "target_weight": 0.1},
    ]
    verdicts, target = normalize_verdicts(raw, ["NVDA", "TSLA", "AAPL"])
    by = {v.ticker: v for v in verdicts}
    assert by["NVDA"].target_weight == -0.2
    assert by["TSLA"].target_weight == 0.15
    assert by["AAPL"].target_weight == 0.0


def test_normalize_clamps_and_scales_gross():
    raw = [
        {"ticker": t, "stance": "LONG", "conviction": 9, "target_weight": 0.5}
        for t in ["NVDA", "TSLA", "AAPL"]
    ]
    verdicts, target = normalize_verdicts(raw, ["NVDA", "TSLA", "AAPL"])
    # 0.5 clamps to 0.25 each = 0.75 gross, within MAX_GROSS: no scaling
    assert all(v.target_weight == 0.25 for v in verdicts)
    assert target.gross == pytest.approx(0.75)
    assert target.cash == pytest.approx(0.25)

    raw5 = [
        {"ticker": t, "stance": "LONG", "conviction": 9, "target_weight": 0.25}
        for t in ["NVDA", "TSLA", "AAPL", "AMZN", "INTC"]
    ]
    verdicts5, target5 = normalize_verdicts(raw5, ["NVDA", "TSLA", "AAPL", "AMZN", "INTC"])
    assert target5.gross == pytest.approx(1.0)
    assert sum(abs(v.target_weight) for v in verdicts5) == pytest.approx(1.0, abs=1e-3)


def test_normalize_fills_missing_and_aliases():
    raw = [{"ticker": "nvda", "stance": "Buy", "conviction": "8", "target_weight": "0.2"}]
    verdicts, _ = normalize_verdicts(raw, ["NVDA", "TSLA"])
    by = {v.ticker: v for v in verdicts}
    assert by["NVDA"].stance == "LONG"
    assert by["NVDA"].conviction == 8
    assert by["TSLA"].stance == "FLAT"
    assert by["TSLA"].target_weight == 0.0


def test_normalize_conviction_clamped():
    raw = [{"ticker": "NVDA", "stance": "LONG", "conviction": 99, "target_weight": 0.1}]
    verdicts, _ = normalize_verdicts(raw, ["NVDA"])
    assert verdicts[0].conviction == 10


# ---------------------------------------------------------------------------
# Fully-mocked end-to-end pipeline (no network, no API key)
# ---------------------------------------------------------------------------

MEMO = "NVDA looks strong. TSLA stretched.\nNVDA — LONG — 8/10 — +20%\nTSLA — SHORT — 6/10 — -10%"
RANKING = "Response A is rigorous. Response B is thin.\n\nFINAL RANKING:\n1. Response A\n2. Response B"
CHAIRMAN = f"The council leans long NVDA, short TSLA.\n\n```json\n{CLEAN_JSON}\n```"


def install_fake_models(monkeypatch, chairman_text=CHAIRMAN):
    async def fake_query_model(model, messages, timeout=120.0, extra_payload=None):
        return {"content": chairman_text, "reasoning_details": None}

    async def fake_query_models_parallel(models, messages, timeout=120.0):
        prompt = messages[0]["content"]
        text = RANKING if "FINAL RANKING" in prompt else MEMO
        return {m: {"content": text, "reasoning_details": None} for m in models}

    monkeypatch.setattr(council_runner, "query_model", fake_query_model)
    monkeypatch.setattr(council_runner, "query_models_parallel", fake_query_models_parallel)


@pytest.mark.asyncio
async def test_full_pipeline_mocked(monkeypatch, synthetic_prices):
    install_fake_models(monkeypatch)
    run = await run_stock_council(
        as_of=date(2025, 6, 2), kind="dry_run", prices=synthetic_prices
    )
    assert run.status == "complete", run.error
    assert run.as_of == "2025-06-02"
    assert {v.ticker for v in run.verdicts} == {"NVDA", "TSLA"}
    assert run.portfolio_target.gross <= 1.0
    assert run.label_to_model  # stage 2 anonymization happened
    assert run.aggregate_rankings
    # Point-in-time guarantee surfaced in the stored run
    assert run.data_summary["point_in_time_only"] is True
    for snap in run.data_summary["snapshots"]:
        assert snap["as_of_trading_day"] <= "2025-06-02"


@pytest.mark.asyncio
async def test_pipeline_rescue_path(monkeypatch, synthetic_prices):
    """Chairman emits unparseable prose; the cheap-model rescue saves the run."""
    calls = {"rescue": 0}

    async def fake_query_model(model, messages, timeout=120.0, extra_payload=None):
        prompt = messages[0]["content"]
        if prompt.startswith("Extract the stock verdicts"):
            calls["rescue"] += 1
            return {"content": CLEAN_JSON, "reasoning_details": None}
        return {"content": "I refuse to emit JSON today.", "reasoning_details": None}

    async def fake_query_models_parallel(models, messages, timeout=120.0):
        prompt = messages[0]["content"]
        text = RANKING if "FINAL RANKING" in prompt else MEMO
        return {m: {"content": text, "reasoning_details": None} for m in models}

    monkeypatch.setattr(council_runner, "query_model", fake_query_model)
    monkeypatch.setattr(council_runner, "query_models_parallel", fake_query_models_parallel)

    run = await run_stock_council(
        as_of=date(2025, 6, 2), kind="dry_run", prices=synthetic_prices
    )
    assert run.status == "complete", run.error
    assert calls["rescue"] == 1


@pytest.mark.asyncio
async def test_pipeline_failure_preserves_raw_text(monkeypatch, synthetic_prices):
    """Both chairman and rescue fail: run is failed but raw stage3 is kept."""
    async def fake_query_model(model, messages, timeout=120.0, extra_payload=None):
        return {"content": "absolutely no structure", "reasoning_details": None}

    async def fake_query_models_parallel(models, messages, timeout=120.0):
        prompt = messages[0]["content"]
        text = RANKING if "FINAL RANKING" in prompt else MEMO
        return {m: {"content": text, "reasoning_details": None} for m in models}

    monkeypatch.setattr(council_runner, "query_model", fake_query_model)
    monkeypatch.setattr(council_runner, "query_models_parallel", fake_query_models_parallel)

    run = await run_stock_council(
        as_of=date(2025, 6, 2), kind="dry_run", prices=synthetic_prices
    )
    assert run.status == "failed"
    assert "parse" in run.error.lower()
    assert run.stage3["response"] == "absolutely no structure"
