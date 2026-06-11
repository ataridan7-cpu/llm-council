"""Configuration for the LLM Council."""

import os
from dotenv import load_dotenv

load_dotenv()

# OpenRouter API key
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Council members - list of OpenRouter model identifiers
COUNCIL_MODELS = [
    "openai/gpt-5.1",
    "google/gemini-3-pro-preview",
    "anthropic/claude-sonnet-4.5",
    "x-ai/grok-4",
]

# Chairman model - synthesizes final response
CHAIRMAN_MODEL = "google/gemini-3-pro-preview"

# OpenRouter API endpoint
OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Data directory for conversation storage
DATA_DIR = "data/conversations"

# Stage 0 research agents - cheap/fast models, one per analyst role
RESEARCH_MODELS = {
    "fundamentals": "google/gemini-2.5-flash",
    "technical": "google/gemini-2.5-flash",
    "news": "openai/gpt-5-mini",
}

# Cheap model for utility calls (JSON repair, quick signals)
REPAIR_MODEL = "google/gemini-2.5-flash"

# Data directories for stock analysis features
ANALYSES_DIR = "data/analyses"
PREDICTIONS_DIR = "data/predictions"
CACHE_DIR = "data/cache/market"
WATCHLIST_PATH = "data/watchlist.json"

# Market data cache TTLs in seconds
CACHE_TTLS = {
    "quote": 300,
    "history": 3600,
    "fundamentals": 86400,
    "news": 1800,
}

# A return within ±HOLD_BAND counts as "flat" (hold was correct)
HOLD_BAND = 0.02

# Optional fallback data source (free tier, 25 req/day)
ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")

# Watchlist refresh: set to "true" to add a one-call cheap-model signal per ticker
WATCHLIST_QUICK_SIGNAL = os.getenv("WATCHLIST_QUICK_SIGNAL", "false").lower() == "true"

# Daily background jobs (outcome evaluation, watchlist refresh)
ENABLE_SCHEDULER = os.getenv("ENABLE_SCHEDULER", "false").lower() == "true"
