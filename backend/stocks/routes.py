"""API routes for the stock council, mounted under /api/stocks."""

import asyncio
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import backfill, store
from .config import (
    TICKERS,
    BENCHMARK,
    ANALYST_MODELS,
    STOCK_CHAIRMAN_MODEL,
    ENABLE_SCHEDULER,
)
from .council_runner import run_stock_council
from .data import get_prices
from .portfolio import equity_curve_payload

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

# Curve scopes map to run kinds; "combined" stitches both eras together
_SCOPE_KINDS = {
    "historical": ["historical", "demo", "dry_run"],
    "live": ["live"],
    "combined": ["historical", "demo", "dry_run", "live"],
}


class RunRequest(BaseModel):
    kind: str = "live"  # "live" or "dry_run"


@router.get("/meta")
async def meta() -> Dict[str, Any]:
    return {
        "tickers": TICKERS,
        "benchmark": BENCHMARK,
        "analyst_models": ANALYST_MODELS,
        "chairman_model": STOCK_CHAIRMAN_MODEL,
        "scheduler_enabled": ENABLE_SCHEDULER,
        "run_in_progress": store.RUN_LOCK.locked(),
    }


@router.get("/runs")
async def list_runs():
    return list(reversed(store.list_runs()))  # newest first


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    run = store.load_run(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/verdicts/latest")
async def latest_verdicts():
    run = store.latest_complete_run()
    if run is None:
        raise HTTPException(status_code=404, detail="No complete runs yet")
    return {
        "run_id": run["run_id"],
        "kind": run["kind"],
        "as_of": run["as_of"],
        "verdicts": run.get("verdicts", []),
        "portfolio_target": run.get("portfolio_target"),
    }


@router.post("/run", status_code=202)
async def trigger_run(request: RunRequest):
    if request.kind not in ("live", "dry_run"):
        raise HTTPException(status_code=400, detail="kind must be 'live' or 'dry_run'")
    if store.RUN_LOCK.locked():
        raise HTTPException(status_code=409, detail="A council run is already in progress")

    started = asyncio.Event()
    holder: Dict[str, str] = {}

    async def announce(run_id: str):
        holder["run_id"] = run_id
        started.set()

    async def runner():
        async with store.RUN_LOCK:
            await run_stock_council(kind=request.kind, on_created=announce)

    asyncio.create_task(runner())
    try:
        # The run id exists as soon as the run record is first persisted
        # (price fetch may take a few seconds on a cold cache)
        await asyncio.wait_for(started.wait(), timeout=60)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=500, detail="Run failed to start")
    return {"run_id": holder["run_id"], "status": "running"}


@router.post("/backtest", status_code=202)
async def trigger_backtest(months: int = 12, dry_run: bool = False):
    if store.RUN_LOCK.locked():
        raise HTTPException(status_code=409, detail="A council run is already in progress")

    async def runner():
        async with store.RUN_LOCK:
            await backfill.run_backfill(months=months, dry_run=dry_run)

    asyncio.create_task(runner())
    return {"status": "started", "months": months}


@router.get("/backtest/status")
async def backtest_status():
    return backfill.get_status()


@router.get("/portfolio")
async def portfolio(scope: str = "combined"):
    kinds = _SCOPE_KINDS.get(scope)
    if kinds is None:
        raise HTTPException(status_code=400, detail=f"scope must be one of {list(_SCOPE_KINDS)}")
    runs = store.complete_runs(kinds=kinds)
    if not runs:
        return {"series": {}, "stats": {}, "rebalances": [], "scope": scope}
    prices = await asyncio.to_thread(get_prices)
    payload = await asyncio.to_thread(equity_curve_payload, runs, prices)
    payload["scope"] = scope
    payload["kinds_included"] = sorted({r["kind"] for r in runs})
    return payload


@router.get("/prices/latest")
async def latest_prices():
    prices = await asyncio.to_thread(get_prices)
    out = []
    for ticker in TICKERS:
        if ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if len(series) < 2:
            continue
        last, prev = float(series.iloc[-1]), float(series.iloc[-2])
        out.append({
            "ticker": ticker,
            "close": round(last, 2),
            "change_pct": round((last / prev - 1) * 100, 2),
            "date": str(series.index[-1].date()),
        })
    return out
