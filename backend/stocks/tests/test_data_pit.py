"""Point-in-time discipline: snapshots must never see data after as_of."""

from datetime import date

import pandas as pd
import pytest

from ..data import build_snapshot, snap_to_trading_day, generate_synthetic_prices


def test_snapshot_identical_when_future_is_truncated(synthetic_prices):
    """The PIT proof: a snapshot built from the full history equals one
    built from history truncated at as_of — future data cannot leak."""
    as_of = date(2025, 3, 10)
    truncated = synthetic_prices.loc[: pd.Timestamp(as_of)]
    for ticker in ["NVDA", "TSLA", "AAPL"]:
        full = build_snapshot(ticker, as_of, synthetic_prices)
        trunc = build_snapshot(ticker, as_of, truncated)
        assert full == trunc, f"future leakage detected for {ticker}"


def test_snapshot_as_of_never_in_future(synthetic_prices):
    for as_of in [date(2025, 1, 15), date(2025, 7, 4), date(2025, 12, 25)]:
        snap = build_snapshot("NVDA", as_of, synthetic_prices)
        assert snap["as_of_trading_day"] <= str(as_of)


def test_snap_to_trading_day_weekend():
    index = pd.bdate_range("2025-01-06", periods=10)
    # Saturday 2025-01-11 -> Friday 2025-01-10
    assert str(snap_to_trading_day(date(2025, 1, 11), index).date()) == "2025-01-10"
    # A trading day maps to itself
    assert str(snap_to_trading_day(date(2025, 1, 8), index).date()) == "2025-01-08"


def test_snap_before_history_raises():
    index = pd.bdate_range("2025-01-06", periods=10)
    with pytest.raises(ValueError):
        snap_to_trading_day(date(2024, 12, 1), index)


def test_snapshot_features_present(synthetic_prices):
    snap = build_snapshot("NVDA", date(2025, 6, 2), synthetic_prices)
    for key in [
        "last_close",
        "return_1m_pct",
        "return_12m_pct",
        "pct_below_52w_high",
        "realized_vol_60d_annualized_pct",
        "max_drawdown_12m_pct",
    ]:
        assert snap.get(key) is not None, f"missing {key}"


def test_insufficient_history_flagged():
    short = generate_synthetic_prices(start=date(2025, 6, 1), end=date(2025, 6, 20))
    snap = build_snapshot("NVDA", date(2025, 6, 18), short)
    assert "error" in snap
