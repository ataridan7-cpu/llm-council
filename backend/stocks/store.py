"""JSON persistence for stock council runs.

Atomic writes (tmp + os.replace) plus a process-wide asyncio lock so only
one council run executes at a time. Single uvicorn worker assumed.
"""

import asyncio
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

from .config import RUNS_DIR, INDEX_JSON
from .schemas import CouncilRun

# Held for the duration of a council run / backfill so concurrent API calls
# get a 409 instead of corrupting state
RUN_LOCK = asyncio.Lock()


def _atomic_write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=os.path.dirname(path), prefix=".tmp_", suffix=".json"
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except BaseException:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def _read_json(path: str) -> Optional[Any]:
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def run_path(run_id: str) -> str:
    return os.path.join(RUNS_DIR, f"{run_id}.json")


def save_run(run: CouncilRun) -> None:
    """Persist a run and refresh its entry in the index."""
    _atomic_write_json(run_path(run.run_id), run.model_dump())
    index = _read_json(INDEX_JSON) or []
    index = [e for e in index if e.get("run_id") != run.run_id]
    index.append(run.index_entry())
    index.sort(key=lambda e: (e.get("as_of", ""), e.get("created_at", "")))
    _atomic_write_json(INDEX_JSON, index)


def load_run(run_id: str) -> Optional[Dict[str, Any]]:
    return _read_json(run_path(run_id))


def list_runs() -> List[Dict[str, Any]]:
    """Run metadata entries, sorted by as_of date ascending."""
    return _read_json(INDEX_JSON) or []


def complete_runs(kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """Full run payloads with status=complete, optionally filtered by kind."""
    runs = []
    for entry in list_runs():
        if entry.get("status") != "complete":
            continue
        if kinds and entry.get("kind") not in kinds:
            continue
        run = load_run(entry["run_id"])
        if run:
            runs.append(run)
    return runs


def latest_complete_run() -> Optional[Dict[str, Any]]:
    """Most recent complete run, preferring live over other kinds."""
    entries = [e for e in list_runs() if e.get("status") == "complete"]
    if not entries:
        return None
    live = [e for e in entries if e.get("kind") == "live"]
    pool = live or entries
    best = max(pool, key=lambda e: (e.get("as_of", ""), e.get("created_at", "")))
    return load_run(best["run_id"])
