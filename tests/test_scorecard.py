"""Tests for scoring and leaderboard logic."""

import pytest
from backend.scorecard import score_one

HOLD_BAND = 0.02


class TestScoreOne:
    def _verdict(self, call: str, direction: str = "up") -> dict:
        return {
            "verdict": call,
            "confidence": 70,
            "price_targets": {
                "1w": {"direction": direction, "low": 95.0, "high": 110.0},
                "1m": {"direction": direction, "low": 95.0, "high": 110.0},
                "3m": {"direction": direction, "low": 95.0, "high": 110.0},
            },
            "thesis": "test",
            "key_risks": [],
        }

    # --- buy ---
    def test_buy_correct(self):
        result = score_one(self._verdict("buy", "up"), 100.0, 105.0, "1m")
        assert result["verdict_hit"] is True
        assert result["direction_hit"] is True
        assert result["return"] == pytest.approx(0.05)

    def test_buy_wrong_down(self):
        result = score_one(self._verdict("buy", "up"), 100.0, 93.0, "1m")
        assert result["verdict_hit"] is False
        assert result["direction_hit"] is False

    def test_buy_within_hold_band(self):
        # +1% — within hold band, so verdict was "buy" but return ≤ band = wrong
        result = score_one(self._verdict("buy", "up"), 100.0, 101.0, "1m")
        assert result["verdict_hit"] is False

    # --- sell ---
    def test_sell_correct(self):
        result = score_one(self._verdict("sell", "down"), 100.0, 93.0, "1m")
        assert result["verdict_hit"] is True
        assert result["direction_hit"] is True

    def test_sell_wrong_up(self):
        result = score_one(self._verdict("sell", "down"), 100.0, 110.0, "1m")
        assert result["verdict_hit"] is False

    # --- hold ---
    def test_hold_correct_flat(self):
        result = score_one(self._verdict("hold", "flat"), 100.0, 101.5, "1m")
        assert result["verdict_hit"] is True  # 1.5% is within ±2% band

    def test_hold_wrong_big_move(self):
        result = score_one(self._verdict("hold", "flat"), 100.0, 106.0, "1m")
        assert result["verdict_hit"] is False  # +6% breaks the hold band

    # --- target range ---
    def test_target_in_range(self):
        result = score_one(self._verdict("buy", "up"), 100.0, 103.0, "1m")
        assert result["target_in_range"] is True  # 103 is between 95–110

    def test_target_out_of_range(self):
        result = score_one(self._verdict("buy", "up"), 100.0, 115.0, "1m")
        assert result["target_in_range"] is False  # 115 > 110

    # --- null handling ---
    def test_none_verdict_returns_nulls(self):
        result = score_one(None, 100.0, 105.0, "1m")
        assert result["direction_hit"] is None
        assert result["verdict_hit"] is None

    def test_zero_price_at(self):
        result = score_one(self._verdict("buy"), 0, 105.0, "1m")
        assert result["return"] is None
