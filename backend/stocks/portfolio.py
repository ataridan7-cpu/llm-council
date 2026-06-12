"""Paper long/short portfolio engine.

Mechanics (documented simplifications):
- Rebalance to target weights at the close of each run's as_of trading day;
  positions drift until the next rebalance.
- Dollar accounting handles shorts naturally: position p_i = w_i * equity
  (negative for shorts), cash = equity - sum(p_i), so short proceeds sit in
  cash. Daily, p_i scales by the price relative; equity = cash + sum(p_i).
- Costs: FEE_BPS on turnover at each rebalance. No cash interest, no short
  borrow cost.
- The equity curve is recomputed on read from stored verdicts + the price
  cache — there is no mutable equity state to corrupt.
"""

from datetime import date
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from .config import FEE_BPS, BENCHMARK, TICKERS
from .data import snap_to_trading_day


def _to_points(series: pd.Series) -> List[Dict[str, float]]:
    """ApexCharts-ready [{x: epoch_ms, y: value}, ...]."""
    return [
        {"x": int(ts.timestamp() * 1000), "y": round(float(v), 4)}
        for ts, v in series.items()
        if not pd.isna(v)
    ]


def _snap_rebalances(
    rebalances: List[Dict[str, Any]], index: pd.DatetimeIndex
) -> List[Tuple[pd.Timestamp, Dict[str, float]]]:
    """Snap rebalance dates to trading days; on collisions keep the later run."""
    snapped: Dict[pd.Timestamp, Dict[str, float]] = {}
    for reb in sorted(rebalances, key=lambda r: str(r["as_of"])):
        d = pd.Timestamp(str(reb["as_of"])).date()
        try:
            ts = snap_to_trading_day(d, index)
        except ValueError:
            continue
        snapped[ts] = {t: float(w) for t, w in reb["weights"].items()}
    return sorted(snapped.items())


def simulate_portfolio(
    rebalances: List[Dict[str, Any]],
    prices: pd.DataFrame,
    end: Optional[date] = None,
    initial: float = 100.0,
    fee_bps: float = FEE_BPS,
) -> pd.Series:
    """Equity series from a sequence of {as_of, weights} rebalances.

    Weights are signed (negative = short). Tickers without a price on a
    rebalance day have their allocation left in cash.
    """
    if not rebalances:
        return pd.Series(dtype=float)

    snapped = _snap_rebalances(rebalances, prices.index)
    if not snapped:
        return pd.Series(dtype=float)

    start_ts = snapped[0][0]
    end_ts = snap_to_trading_day(end, prices.index) if end else prices.index[-1]
    days = prices.index[(prices.index >= start_ts) & (prices.index <= end_ts)]
    rebalance_map = dict(snapped)

    positions: Dict[str, float] = {}
    cash = initial
    equity = initial
    prev_day: Optional[pd.Timestamp] = None
    values = []

    for day in days:
        # Drift existing positions by the day's price relative
        if prev_day is not None:
            for ticker in list(positions):
                p0 = prices.at[prev_day, ticker]
                p1 = prices.at[day, ticker]
                if not pd.isna(p0) and not pd.isna(p1) and p0 != 0:
                    positions[ticker] *= float(p1 / p0)
            equity = cash + sum(positions.values())

        if day in rebalance_map:
            targets = {}
            for ticker, w in rebalance_map[day].items():
                px = prices.at[day, ticker] if ticker in prices.columns else None
                if w != 0 and px is not None and not pd.isna(px):
                    targets[ticker] = w * equity
            turnover = sum(
                abs(targets.get(t, 0.0) - positions.get(t, 0.0))
                for t in set(targets) | set(positions)
            )
            fee = turnover * fee_bps / 10_000
            equity -= fee
            # Re-scale targets to post-fee equity so weights stay exact
            scale = equity / (equity + fee) if (equity + fee) > 0 else 1.0
            positions = {t: v * scale for t, v in targets.items()}
            cash = equity - sum(positions.values())

        values.append((day, equity))
        prev_day = day

    return pd.Series(dict(values), name="council")


def benchmark_curves(
    prices: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
    initial: float = 100.0,
    tickers: Optional[List[str]] = None,
) -> Dict[str, pd.Series]:
    """SPY buy & hold and equal-weight-1/N buy & hold (never rebalanced)."""
    tickers = tickers or TICKERS
    window = prices.loc[start:end]
    out: Dict[str, pd.Series] = {}

    spy = window[BENCHMARK].dropna()
    if len(spy):
        out["spy"] = initial * spy / spy.iloc[0]

    held = [t for t in tickers if t in window.columns and not pd.isna(window[t].iloc[0])]
    if held:
        per_name = initial / len(held)
        eq = sum(per_name * window[t] / window[t].iloc[0] for t in held)
        out["equal_weight"] = eq.dropna()

    return out


def compute_stats(series: pd.Series) -> Dict[str, Any]:
    """Summary stats for one equity curve."""
    if series is None or len(series) < 2:
        return {}
    returns = series.pct_change().dropna()
    running_max = series.cummax()
    drawdown = (series / running_max - 1).min()
    ann_vol = float(returns.std() * (252 ** 0.5))
    sharpe = (
        float(returns.mean() / returns.std() * (252 ** 0.5))
        if returns.std() > 0
        else None
    )
    return {
        "start": str(series.index[0].date()),
        "end": str(series.index[-1].date()),
        "total_return_pct": round((float(series.iloc[-1] / series.iloc[0]) - 1) * 100, 2),
        "max_drawdown_pct": round(float(drawdown) * 100, 2),
        "annualized_vol_pct": round(ann_vol * 100, 2),
        "sharpe_naive": round(sharpe, 2) if sharpe is not None else None,
    }


def hit_rate_vs_benchmark(
    council: pd.Series,
    benchmark: pd.Series,
    rebalance_dates: List[pd.Timestamp],
) -> Optional[float]:
    """Fraction of inter-rebalance periods where the council beat the benchmark."""
    marks = [d for d in rebalance_dates if d in council.index and d in benchmark.index]
    if len(marks) < 2:
        marks = marks + [council.index[-1]] if len(marks) == 1 else marks
    if len(marks) < 2:
        return None
    wins = total = 0
    for a, b in zip(marks, marks[1:]):
        c_ret = council.loc[b] / council.loc[a]
        b_ret = benchmark.loc[b] / benchmark.loc[a]
        total += 1
        if c_ret > b_ret:
            wins += 1
    return round(wins / total, 3) if total else None


def equity_curve_payload(
    runs: List[Dict[str, Any]],
    prices: pd.DataFrame,
    end: Optional[date] = None,
    initial: float = 100.0,
) -> Dict[str, Any]:
    """Full API payload: council vs SPY vs equal-weight + stats + rebalances.

    `runs` are stored CouncilRun dicts with status=complete; their
    portfolio_target.weights drive the rebalances.
    """
    rebalances = [
        {"as_of": r["as_of"], "weights": (r.get("portfolio_target") or {}).get("weights", {})}
        for r in runs
        if r.get("portfolio_target")
    ]
    council = simulate_portfolio(rebalances, prices, end=end, initial=initial)
    if council.empty:
        return {"series": {}, "stats": {}, "rebalances": []}

    benches = benchmark_curves(prices, council.index[0], council.index[-1], initial)
    snapped = _snap_rebalances(rebalances, prices.index)
    rebalance_dates = [ts for ts, _ in snapped]

    series = {"council": _to_points(council)}
    stats = {"council": compute_stats(council)}
    for name, curve in benches.items():
        series[name] = _to_points(curve)
        stats[name] = compute_stats(curve)
    if "spy" in benches:
        stats["council"]["hit_rate_vs_spy"] = hit_rate_vs_benchmark(
            council, benches["spy"], rebalance_dates
        )

    return {
        "series": series,
        "stats": stats,
        "rebalances": [
            {"date": str(ts.date()), "weights": w} for ts, w in snapped
        ],
    }
