"""Tests for pure-python market data helpers (no network calls)."""

import pytest
from backend.market_data import compute_indicators, _sma, _rsi, _trailing_return


def _candles(closes):
    """Build minimal candle list from a list of close prices."""
    return [
        {"date": f"2026-01-{i+1:02d}", "open": c, "high": c + 1,
         "low": c - 1, "close": c, "volume": 1_000_000}
        for i, c in enumerate(closes)
    ]


class TestSma:
    def test_basic(self):
        assert _sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == pytest.approx(4.0)

    def test_insufficient_data(self):
        assert _sma([1.0, 2.0], 5) is None

    def test_exact_window(self):
        assert _sma([10.0, 20.0, 30.0], 3) == pytest.approx(20.0)


class TestRsi:
    def test_all_up_returns_100(self):
        closes = [float(i) for i in range(1, 20)]  # strictly rising
        result = _rsi(closes, 14)
        assert result == pytest.approx(100.0)

    def test_all_down_returns_0(self):
        closes = [float(i) for i in range(20, 1, -1)]  # strictly falling
        result = _rsi(closes, 14)
        assert result == pytest.approx(0.0)

    def test_insufficient_data(self):
        assert _rsi([1.0, 2.0, 3.0], 14) is None


class TestTrailingReturn:
    def test_positive_return(self):
        closes = [100.0] * 10 + [110.0]
        assert _trailing_return(closes, 5) == pytest.approx(0.1)

    def test_negative_return(self):
        closes = [100.0] * 10 + [90.0]
        assert _trailing_return(closes, 5) == pytest.approx(-0.1)

    def test_insufficient_data(self):
        assert _trailing_return([100.0, 110.0], 5) is None


class TestComputeIndicators:
    def test_basic_keys(self):
        closes = [float(100 + i) for i in range(250)]
        ind = compute_indicators(_candles(closes))
        assert "last_close" in ind
        assert "sma20" in ind
        assert "sma50" in ind
        assert "sma200" in ind
        assert "rsi14" in ind
        assert "high_52w" in ind
        assert "low_52w" in ind
        assert "return_1w" in ind
        assert "return_1m" in ind
        assert "return_3m" in ind

    def test_empty_returns_empty(self):
        assert compute_indicators([]) == {}

    def test_values_are_sane(self):
        closes = [float(100 + i) for i in range(250)]
        ind = compute_indicators(_candles(closes))
        assert ind["last_close"] == 349.0
        assert ind["high_52w"] >= ind["last_close"]
        assert ind["low_52w"] <= ind["last_close"]
        assert 0 <= ind["rsi14"] <= 100
