"""Shared fixtures: tmp-dir storage and deterministic synthetic prices."""

import os

import pandas as pd
import pytest

from .. import store


@pytest.fixture(autouse=True)
def tmp_storage(tmp_path, monkeypatch):
    """Redirect all JSON persistence into a per-test temp dir."""
    monkeypatch.setattr(store, "RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setattr(store, "INDEX_JSON", str(tmp_path / "index.json"))
    yield tmp_path


@pytest.fixture
def flat_prices():
    """Two years of business days; every ticker pinned at 100."""
    from ..config import TICKERS, BENCHMARK

    index = pd.bdate_range("2024-01-01", "2026-01-01")
    return pd.DataFrame(100.0, index=index, columns=TICKERS + [BENCHMARK])


@pytest.fixture
def synthetic_prices():
    from ..data import generate_synthetic_prices
    from datetime import date

    return generate_synthetic_prices(
        start=date(2024, 1, 1), end=date(2026, 1, 1), seed=7
    )
