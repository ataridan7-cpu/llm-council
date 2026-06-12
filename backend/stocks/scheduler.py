"""Weekly live council scheduling via APScheduler.

Wired into FastAPI through a lifespan context. The manual "Run council"
button remains the primary path for a locally-run app (the machine may be
asleep at cron time); the scheduler covers always-on setups and fires a
catch-up run on startup if the newest live run is older than a week.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from .config import ENABLE_SCHEDULER
from . import store

_scheduler = None


async def _scheduled_live_run():
    from .council_runner import run_stock_council

    if store.RUN_LOCK.locked():
        print("Scheduler: skipping live run, another run is in progress")
        return
    async with store.RUN_LOCK:
        run = await run_stock_council(kind="live")
        print(f"Scheduler: live run {run.run_id} finished with status={run.status}")


def _days_since_last_live_run() -> float:
    live = [
        e for e in store.list_runs()
        if e.get("kind") == "live" and e.get("status") == "complete"
    ]
    if not live:
        return float("inf")
    newest = max(e["created_at"] for e in live)
    try:
        dt = datetime.fromisoformat(newest)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - dt).total_seconds() / 86400
    except ValueError:
        return float("inf")


@asynccontextmanager
async def stocks_lifespan(app):
    global _scheduler
    import os

    if ENABLE_SCHEDULER and os.getenv("OPENROUTER_API_KEY"):
        from apscheduler.schedulers.asyncio import AsyncIOScheduler
        from apscheduler.triggers.cron import CronTrigger

        _scheduler = AsyncIOScheduler()
        # Monday 22:00 UTC, after the US market close
        _scheduler.add_job(
            _scheduled_live_run,
            CronTrigger(day_of_week="mon", hour=22, minute=0, timezone="UTC"),
            id="weekly_live_council",
        )
        if _days_since_last_live_run() > 7:
            _scheduler.add_job(_scheduled_live_run, id="startup_catchup")
        _scheduler.start()
        print("Stock council scheduler started (weekly live run: Mon 22:00 UTC)")
    elif ENABLE_SCHEDULER:
        print("Stock council scheduler disabled: OPENROUTER_API_KEY not set")

    yield

    if _scheduler is not None:
        _scheduler.shutdown(wait=False)


def scheduler_running() -> bool:
    return _scheduler is not None and _scheduler.running
