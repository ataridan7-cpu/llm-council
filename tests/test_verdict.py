"""Tests for verdict JSON extraction and parsing."""

import pytest
from backend.verdict import extract_verdict_json, StockVerdict
from pydantic import ValidationError


def _make_response(json_str: str, preamble: str = "Some analysis text.") -> str:
    return f"{preamble}\n\nFINAL VERDICT:\n```json\n{json_str}\n```"


VALID_VERDICT = {
    "verdict": "buy",
    "confidence": 75,
    "price_targets": {
        "1w": {"direction": "up", "low": 290.0, "high": 310.0},
        "1m": {"direction": "up", "low": 300.0, "high": 340.0},
        "3m": {"direction": "up", "low": 310.0, "high": 380.0},
    },
    "thesis": "Strong fundamentals and AI tailwinds support upside.",
    "key_risks": ["macro headwinds", "valuation stretch"],
}


class TestExtractVerdictJson:
    def test_fenced_block(self):
        import json
        text = _make_response(json.dumps(VALID_VERDICT))
        result = extract_verdict_json(text)
        assert result is not None
        assert result["verdict"] == "buy"

    def test_fenced_block_without_language_tag(self):
        import json
        text = f"Analysis.\n\nFINAL VERDICT:\n```\n{json.dumps(VALID_VERDICT)}\n```"
        result = extract_verdict_json(text)
        assert result is not None
        assert result["confidence"] == 75

    def test_last_fence_wins_multiple_fences(self):
        import json
        first = json.dumps({"verdict": "sell", "confidence": 30,
                            "price_targets": {"1w": {"direction": "down"}, "1m": {"direction": "down"}, "3m": {"direction": "down"}},
                            "thesis": "old"})
        second = json.dumps(VALID_VERDICT)
        text = f"```json\n{first}\n```\n\nFINAL VERDICT:\n```json\n{second}\n```"
        result = extract_verdict_json(text)
        assert result["verdict"] == "buy"

    def test_balanced_brace_fallback(self):
        import json
        blob = json.dumps(VALID_VERDICT)
        text = f"No fences here. FINAL VERDICT: {blob}"
        result = extract_verdict_json(text)
        assert result is not None
        assert result["verdict"] == "buy"

    def test_returns_none_on_empty(self):
        assert extract_verdict_json("") is None
        assert extract_verdict_json(None) is None

    def test_returns_none_on_garbage(self):
        assert extract_verdict_json("no json here at all") is None


class TestStockVerdict:
    def test_valid_verdict(self):
        v = StockVerdict.model_validate(VALID_VERDICT)
        assert v.verdict == "buy"
        assert v.confidence == 75
        assert v.price_targets["1w"].direction == "up"
        assert v.price_targets["1w"].low == 290.0

    def test_invalid_verdict_type(self):
        bad = {**VALID_VERDICT, "verdict": "strong_buy"}
        with pytest.raises(ValidationError):
            StockVerdict.model_validate(bad)

    def test_confidence_out_of_range(self):
        bad = {**VALID_VERDICT, "confidence": 150}
        with pytest.raises(ValidationError):
            StockVerdict.model_validate(bad)

    def test_missing_price_targets(self):
        bad = {**VALID_VERDICT}
        del bad["price_targets"]
        with pytest.raises(ValidationError):
            StockVerdict.model_validate(bad)

    def test_null_low_high_allowed(self):
        import copy
        v = copy.deepcopy(VALID_VERDICT)
        v["price_targets"]["1w"]["low"] = None
        v["price_targets"]["1w"]["high"] = None
        result = StockVerdict.model_validate(v)
        assert result.price_targets["1w"].low is None
