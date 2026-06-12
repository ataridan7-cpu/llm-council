"""Closed-form checks of the long/short portfolio engine."""

import pandas as pd
import pytest

from ..portfolio import (
    simulate_portfolio,
    benchmark_curves,
    compute_stats,
    equity_curve_payload,
)


def make_prices(days, **paths):
    index = pd.bdate_range("2025-01-06", periods=days)  # starts on a Monday
    return pd.DataFrame({t: vals for t, vals in paths.items()}, index=index)


def test_long_only_matches_closed_form():
    # 100% long a stock rising 1%/day, no fees: equity = 100 * 1.01^n
    n = 10
    prices = make_prices(n, AAA=[100 * 1.01 ** i for i in range(n)])
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"AAA": 1.0}}], prices, fee_bps=0
    )
    assert len(curve) == n
    assert curve.iloc[0] == pytest.approx(100.0)
    assert curve.iloc[-1] == pytest.approx(100 * 1.01 ** (n - 1))


def test_short_profits_when_price_falls():
    # 25% short a stock falling 2%/day: equity rises
    n = 10
    prices = make_prices(n, BBB=[100 * 0.98 ** i for i in range(n)])
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"BBB": -0.25}}], prices, fee_bps=0
    )
    assert curve.iloc[-1] > curve.iloc[0]
    # Short P&L: position -25 scales by 0.98^9; equity = cash 125 + position
    expected = 125 - 25 * (0.98 ** 9)
    assert curve.iloc[-1] == pytest.approx(expected)


def test_short_loses_when_price_rises():
    n = 5
    prices = make_prices(n, BBB=[100 * 1.03 ** i for i in range(n)])
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"BBB": -0.25}}], prices, fee_bps=0
    )
    assert curve.iloc[-1] < 100.0


def test_fee_deducted_on_turnover():
    # Flat prices, one rebalance into 50% gross at 100 bps:
    # turnover = 50, fee = 0.5, equity stays 99.5 forever after
    n = 5
    prices = make_prices(n, AAA=[100.0] * n)
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"AAA": 0.5}}], prices, fee_bps=100
    )
    assert curve.iloc[0] == pytest.approx(99.5, abs=0.01)
    assert curve.iloc[-1] == pytest.approx(curve.iloc[0])


def test_cash_remainder_dampens_returns():
    # 50% long +1%/day, 50% cash: daily portfolio return ~0.5%
    n = 6
    prices = make_prices(n, AAA=[100 * 1.01 ** i for i in range(n)])
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"AAA": 0.5}}], prices, fee_bps=0
    )
    day1_ret = curve.iloc[1] / curve.iloc[0] - 1
    assert day1_ret == pytest.approx(0.005, abs=1e-6)


def test_weekend_rebalance_snaps_to_friday():
    prices = make_prices(10, AAA=list(range(100, 110)))
    # 2025-01-11 is a Saturday; should snap to Friday 2025-01-10
    curve = simulate_portfolio(
        [{"as_of": "2025-01-11", "weights": {"AAA": 1.0}}], prices, fee_bps=0
    )
    assert str(curve.index[0].date()) == "2025-01-10"


def test_multiple_rebalances_flip_direction():
    # Long while rising, flip short before the fall: both legs profit
    ups = [100 * 1.02 ** i for i in range(5)]
    downs = [ups[-1] * 0.98 ** i for i in range(1, 6)]
    prices = make_prices(10, CCC=ups + downs)
    flip_day = str(prices.index[4].date())
    curve = simulate_portfolio(
        [
            {"as_of": "2025-01-06", "weights": {"CCC": 0.25}},
            {"as_of": flip_day, "weights": {"CCC": -0.25}},
        ],
        prices,
        fee_bps=0,
    )
    assert curve.iloc[4] > curve.iloc[0]
    assert curve.iloc[-1] > curve.iloc[4]


def test_benchmarks_normalized_to_initial(flat_prices):
    start, end = flat_prices.index[0], flat_prices.index[100]
    curves = benchmark_curves(flat_prices, start, end, initial=100.0)
    assert curves["spy"].iloc[0] == pytest.approx(100.0)
    assert curves["equal_weight"].iloc[0] == pytest.approx(100.0)
    assert curves["equal_weight"].iloc[-1] == pytest.approx(100.0)  # flat prices


def test_stats_shapes():
    n = 30
    prices = make_prices(n, AAA=[100 * 1.005 ** i for i in range(n)])
    curve = simulate_portfolio(
        [{"as_of": "2025-01-06", "weights": {"AAA": 1.0}}], prices, fee_bps=0
    )
    stats = compute_stats(curve)
    assert stats["total_return_pct"] > 0
    assert stats["max_drawdown_pct"] == pytest.approx(0.0)
    assert "sharpe_naive" in stats


def test_equity_curve_payload_shape(synthetic_prices):
    runs = [
        {
            "as_of": "2025-03-03",
            "portfolio_target": {"weights": {"NVDA": 0.2, "TSLA": -0.1}},
        },
        {
            "as_of": "2025-06-02",
            "portfolio_target": {"weights": {"NVDA": 0.1, "AAPL": 0.15}},
        },
    ]
    payload = equity_curve_payload(runs, synthetic_prices)
    assert set(payload["series"]) == {"council", "spy", "equal_weight"}
    point = payload["series"]["council"][0]
    assert set(point) == {"x", "y"}  # ApexCharts {x, y} contract
    assert isinstance(point["x"], int)
    assert len(payload["rebalances"]) == 2
    assert "hit_rate_vs_spy" in payload["stats"]["council"]
