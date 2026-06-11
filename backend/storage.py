"""JSON-based storage for conversations, analyses, and predictions."""

import json
import os
from datetime import datetime
from typing import List, Dict, Any, Optional
from pathlib import Path
from .config import DATA_DIR, ANALYSES_DIR, PREDICTIONS_DIR


def ensure_data_dir():
    """Ensure the data directory exists."""
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)


def get_conversation_path(conversation_id: str) -> str:
    """Get the file path for a conversation."""
    return os.path.join(DATA_DIR, f"{conversation_id}.json")


def create_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Create a new conversation.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        New conversation dict
    """
    ensure_data_dir()

    conversation = {
        "id": conversation_id,
        "created_at": datetime.utcnow().isoformat(),
        "title": "New Conversation",
        "messages": []
    }

    # Save to file
    path = get_conversation_path(conversation_id)
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)

    return conversation


def get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
    """
    Load a conversation from storage.

    Args:
        conversation_id: Unique identifier for the conversation

    Returns:
        Conversation dict or None if not found
    """
    path = get_conversation_path(conversation_id)

    if not os.path.exists(path):
        return None

    with open(path, 'r') as f:
        return json.load(f)


def save_conversation(conversation: Dict[str, Any]):
    """
    Save a conversation to storage.

    Args:
        conversation: Conversation dict to save
    """
    ensure_data_dir()

    path = get_conversation_path(conversation['id'])
    with open(path, 'w') as f:
        json.dump(conversation, f, indent=2)


def list_conversations() -> List[Dict[str, Any]]:
    """
    List all conversations (metadata only).

    Returns:
        List of conversation metadata dicts
    """
    ensure_data_dir()

    conversations = []
    for filename in os.listdir(DATA_DIR):
        if filename.endswith('.json'):
            path = os.path.join(DATA_DIR, filename)
            with open(path, 'r') as f:
                data = json.load(f)
                # Return metadata only
                conversations.append({
                    "id": data["id"],
                    "created_at": data["created_at"],
                    "title": data.get("title", "New Conversation"),
                    "message_count": len(data["messages"])
                })

    # Sort by creation time, newest first
    conversations.sort(key=lambda x: x["created_at"], reverse=True)

    return conversations


def add_user_message(conversation_id: str, content: str):
    """
    Add a user message to a conversation.

    Args:
        conversation_id: Conversation identifier
        content: User message content
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "user",
        "content": content
    })

    save_conversation(conversation)


def add_assistant_message(
    conversation_id: str,
    stage1: List[Dict[str, Any]],
    stage2: List[Dict[str, Any]],
    stage3: Dict[str, Any]
):
    """
    Add an assistant message with all 3 stages to a conversation.

    Args:
        conversation_id: Conversation identifier
        stage1: List of individual model responses
        stage2: List of model rankings
        stage3: Final synthesized response
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["messages"].append({
        "role": "assistant",
        "stage1": stage1,
        "stage2": stage2,
        "stage3": stage3
    })

    save_conversation(conversation)


def update_conversation_title(conversation_id: str, title: str):
    """
    Update the title of a conversation.

    Args:
        conversation_id: Conversation identifier
        title: New title for the conversation
    """
    conversation = get_conversation(conversation_id)
    if conversation is None:
        raise ValueError(f"Conversation {conversation_id} not found")

    conversation["title"] = title
    save_conversation(conversation)


# ---------------------------------------------------------------------------
# Analyses
# ---------------------------------------------------------------------------

def _ensure_dir(path: str):
    Path(path).mkdir(parents=True, exist_ok=True)


def _analysis_path(analysis_id: str) -> str:
    return os.path.join(ANALYSES_DIR, f"{analysis_id}.json")


def save_analysis(analysis: Dict[str, Any]):
    _ensure_dir(ANALYSES_DIR)
    with open(_analysis_path(analysis["id"]), 'w') as f:
        json.dump(analysis, f, indent=2)


def get_analysis(analysis_id: str) -> Optional[Dict[str, Any]]:
    path = _analysis_path(analysis_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def list_analyses(ticker: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_dir(ANALYSES_DIR)
    results = []
    for filename in os.listdir(ANALYSES_DIR):
        if not filename.endswith('.json'):
            continue
        with open(os.path.join(ANALYSES_DIR, filename), 'r') as f:
            data = json.load(f)
        if ticker and data.get("ticker") != ticker.upper():
            continue
        verdict = (data.get("stage3") or {}).get("verdict")
        results.append({
            "id": data["id"],
            "ticker": data.get("ticker"),
            "created_at": data.get("created_at"),
            "verdict": (verdict or {}).get("verdict") if verdict else None,
            "confidence": (verdict or {}).get("confidence") if verdict else None,
            "price_at": (data.get("market_snapshot") or {}).get("price"),
            "prediction_id": data.get("prediction_id"),
        })
    results.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return results


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

def _prediction_path(prediction_id: str) -> str:
    return os.path.join(PREDICTIONS_DIR, f"{prediction_id}.json")


def save_prediction(prediction: Dict[str, Any]):
    _ensure_dir(PREDICTIONS_DIR)
    with open(_prediction_path(prediction["id"]), 'w') as f:
        json.dump(prediction, f, indent=2)


def get_prediction(prediction_id: str) -> Optional[Dict[str, Any]]:
    path = _prediction_path(prediction_id)
    if not os.path.exists(path):
        return None
    with open(path, 'r') as f:
        return json.load(f)


def update_prediction(prediction: Dict[str, Any]):
    save_prediction(prediction)


def list_predictions(
    ticker: Optional[str] = None, status: Optional[str] = None
) -> List[Dict[str, Any]]:
    _ensure_dir(PREDICTIONS_DIR)
    results = []
    for filename in os.listdir(PREDICTIONS_DIR):
        if not filename.endswith('.json'):
            continue
        with open(os.path.join(PREDICTIONS_DIR, filename), 'r') as f:
            data = json.load(f)
        if ticker and data.get("ticker") != ticker.upper():
            continue
        outcomes = data.get("outcomes", {})
        # Filter by status: include if any timeframe matches
        if status:
            if not any(o.get("status") == status for o in outcomes.values()):
                continue
        council_v = (data.get("council_verdict") or {}).get("verdict")
        results.append({
            "id": data["id"],
            "ticker": data.get("ticker"),
            "analysis_id": data.get("analysis_id"),
            "created_at": data.get("created_at"),
            "price_at_prediction": data.get("price_at_prediction"),
            "council_verdict": council_v,
            "outcomes_summary": {
                tf: o.get("status") for tf, o in outcomes.items()
            },
        })
    results.sort(key=lambda x: x["created_at"] or "", reverse=True)
    return results
