"""Tests for storage round-trips (analyses and predictions)."""

import json
import os
import tempfile
import uuid
import pytest

import backend.storage as storage
from backend.config import ANALYSES_DIR, PREDICTIONS_DIR


@pytest.fixture(autouse=True)
def tmp_dirs(tmp_path, monkeypatch):
    """Redirect all storage paths to a temp directory for isolation."""
    analyses = str(tmp_path / "analyses")
    predictions = str(tmp_path / "predictions")
    conversations = str(tmp_path / "conversations")
    monkeypatch.setattr("backend.storage.ANALYSES_DIR", analyses)
    monkeypatch.setattr("backend.config.ANALYSES_DIR", analyses)
    monkeypatch.setattr("backend.storage.PREDICTIONS_DIR", predictions)
    monkeypatch.setattr("backend.config.PREDICTIONS_DIR", predictions)
    monkeypatch.setattr("backend.storage.DATA_DIR", conversations)
    monkeypatch.setattr("backend.config.DATA_DIR", conversations)


def _sample_analysis(ticker="NVDA"):
    aid = str(uuid.uuid4())
    return {
        "id": aid,
        "ticker": ticker,
        "created_at": "2026-06-11T12:00:00",
        "question": "test question",
        "market_snapshot": {"price": 120.50, "currency": "USD", "name": "NVIDIA"},
        "dossier": {"sections": [], "data_used": {}, "dossier_text": ""},
        "stage1": [{"model": "openai/gpt-5-mini", "response": "test", "verdict": None}],
        "stage2": [],
        "stage3": {"model": "google/gemini-2.5-flash", "response": "report",
                   "verdict": {"verdict": "buy", "confidence": 70,
                               "price_targets": {"1w": {"direction": "up", "low": 115.0, "high": 130.0},
                                                 "1m": {"direction": "up", "low": 120.0, "high": 140.0},
                                                 "3m": {"direction": "up", "low": 130.0, "high": 160.0}},
                               "thesis": "t", "key_risks": []}},
        "metadata": {"label_to_model": {}, "aggregate_rankings": []},
        "prediction_id": None,
    }


def _sample_prediction(analysis):
    return {
        "id": str(uuid.uuid4()),
        "ticker": analysis["ticker"],
        "analysis_id": analysis["id"],
        "created_at": analysis["created_at"],
        "price_at_prediction": 120.50,
        "spy_price_at_prediction": 540.0,
        "council_verdict": analysis["stage3"]["verdict"],
        "model_verdicts": [],
        "outcomes": {
            "1w": {"due_at": "2026-06-18T12:00:00", "status": "pending",
                   "actual_price": None, "actual_return": None, "spy_return": None, "alpha": None, "results": {}},
            "1m": {"due_at": "2026-07-11T12:00:00", "status": "pending",
                   "actual_price": None, "actual_return": None, "spy_return": None, "alpha": None, "results": {}},
            "3m": {"due_at": "2026-09-11T12:00:00", "status": "pending",
                   "actual_price": None, "actual_return": None, "spy_return": None, "alpha": None, "results": {}},
        },
    }


class TestAnalysisStorage:
    def test_save_and_get(self):
        a = _sample_analysis()
        storage.save_analysis(a)
        loaded = storage.get_analysis(a["id"])
        assert loaded is not None
        assert loaded["id"] == a["id"]
        assert loaded["ticker"] == "NVDA"

    def test_get_missing_returns_none(self):
        assert storage.get_analysis("nonexistent-id") is None

    def test_list_all(self):
        a1 = _sample_analysis("NVDA")
        a2 = _sample_analysis("AAPL")
        storage.save_analysis(a1)
        storage.save_analysis(a2)
        all_analyses = storage.list_analyses()
        assert len(all_analyses) == 2

    def test_list_filter_by_ticker(self):
        storage.save_analysis(_sample_analysis("NVDA"))
        storage.save_analysis(_sample_analysis("AAPL"))
        nvda = storage.list_analyses(ticker="NVDA")
        assert len(nvda) == 1
        assert nvda[0]["ticker"] == "NVDA"

    def test_list_sorted_newest_first(self):
        a1 = _sample_analysis()
        a1["created_at"] = "2026-01-01T00:00:00"
        a2 = _sample_analysis()
        a2["created_at"] = "2026-06-01T00:00:00"
        storage.save_analysis(a1)
        storage.save_analysis(a2)
        results = storage.list_analyses()
        assert results[0]["created_at"] > results[1]["created_at"]

    def test_overwrite_preserves_id(self):
        a = _sample_analysis()
        storage.save_analysis(a)
        a["prediction_id"] = "pred-123"
        storage.save_analysis(a)
        loaded = storage.get_analysis(a["id"])
        assert loaded["prediction_id"] == "pred-123"


class TestPredictionStorage:
    def test_save_and_get(self):
        a = _sample_analysis()
        p = _sample_prediction(a)
        storage.save_prediction(p)
        loaded = storage.get_prediction(p["id"])
        assert loaded is not None
        assert loaded["ticker"] == "NVDA"
        assert loaded["outcomes"]["1w"]["status"] == "pending"

    def test_update_prediction(self):
        a = _sample_analysis()
        p = _sample_prediction(a)
        storage.save_prediction(p)
        p["outcomes"]["1w"]["status"] = "evaluated"
        p["outcomes"]["1w"]["actual_price"] = 125.0
        p["outcomes"]["1w"]["actual_return"] = 0.037
        p["outcomes"]["1w"]["spy_return"] = 0.01
        p["outcomes"]["1w"]["alpha"] = 0.027
        storage.update_prediction(p)
        loaded = storage.get_prediction(p["id"])
        assert loaded["outcomes"]["1w"]["status"] == "evaluated"
        assert loaded["outcomes"]["1w"]["alpha"] == pytest.approx(0.027)

    def test_list_predictions(self):
        a = _sample_analysis()
        p = _sample_prediction(a)
        storage.save_prediction(p)
        results = storage.list_predictions(ticker="NVDA")
        assert len(results) == 1

    def test_list_filter_status_pending(self):
        a = _sample_analysis()
        p = _sample_prediction(a)
        storage.save_prediction(p)
        pending = storage.list_predictions(status="pending")
        assert len(pending) == 1

    def test_list_filter_status_evaluated_empty(self):
        a = _sample_analysis()
        p = _sample_prediction(a)
        storage.save_prediction(p)
        evaluated = storage.list_predictions(status="evaluated")
        assert len(evaluated) == 0
