"""Resumable 12-month historical simulation driver.

Runs one historical council per month (first trading day), feeding only
point-in-time data. Skips dates that already have a complete run, so a
crashed or interrupted backfill just picks up where it left off.

CLI: python -m backend.stocks.backfill [--months 12] [--dry-run]
"""

import argparse
import asyncio
from datetime import date
from typing import Any, Dict, List, Optional

import pandas as pd

from . import store
from .council_runner import run_stock_council
from .data import get_prices

# In-memory progress for GET /api/stocks/backtest/status
_STATUS: Dict[str, Any] = {"state": "idle", "completed": 0, "total": 0, "current_as_of": None}


def get_status() -> Dict[str, Any]:
    return dict(_STATUS)


def historical_run_dates(prices: pd.DataFrame, months: int = 12) -> List[date]:
    """First trading day of each of the last `months` months (oldest first)."""
    by_month = prices.index.to_series().groupby(
        [prices.index.year, prices.index.month]
    ).min()
    return [ts.date() for ts in by_month.sort_values().tail(months)]


def _existing_complete_dates(kind: str) -> set:
    return {
        e["as_of"]
        for e in store.list_runs()
        if e.get("kind") == kind and e.get("status") == "complete"
    }


async def run_backfill(months: int = 12, dry_run: bool = False) -> Dict[str, Any]:
    """Run the historical sim, resuming past completed dates."""
    kind = "dry_run" if dry_run else "historical"
    prices = get_prices()
    dates = historical_run_dates(prices, months)
    done = _existing_complete_dates(kind)

    _STATUS.update(state="running", completed=0, total=len(dates), current_as_of=None)
    completed = 0
    failures = []
    try:
        for d in dates:
            if str(d) in done:
                completed += 1
                _STATUS.update(completed=completed)
                continue
            _STATUS.update(current_as_of=str(d))
            run = await run_stock_council(as_of=d, kind=kind, prices=prices)
            if run.status == "complete":
                completed += 1
            else:
                failures.append({"as_of": str(d), "error": run.error})
            _STATUS.update(completed=completed)
    finally:
        _STATUS.update(
            state="idle" if not failures else "completed_with_errors",
            current_as_of=None,
        )
        if completed == len(dates):
            _STATUS.update(state="done")

    return {"completed": completed, "total": len(dates), "failures": failures}


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 12-month historical simulation")
    parser.add_argument("--months", type=int, default=12)
    parser.add_argument("--dry-run", action="store_true",
                        help="cheap models + 2 tickers, for pipeline validation")
    args = parser.parse_args()

    result = asyncio.run(run_backfill(months=args.months, dry_run=args.dry_run))
    print(f"Backfill: {result['completed']}/{result['total']} complete")
    for f in result["failures"]:
        print(f"  FAILED {f['as_of']}: {f['error']}")


if __name__ == "__main__":
    main()
