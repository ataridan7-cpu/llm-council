"""Configuration for the stock prediction council."""

import os

from ..config import COUNCIL_MODELS, CHAIRMAN_MODEL

# The fixed universe of stocks the council deliberates on
TICKERS = ["NVDA", "INTC", "AMD", "AMZN", "AAPL", "TSLA", "NFLX"]

# Benchmark for the equity-curve comparison (dividend-adjusted via auto_adjust)
BENCHMARK = "SPY"

# Model tiers: strong models do analysis/ranking/synthesis, the cheap model
# is used only for parsing rescue (extracting JSON from malformed output)
ANALYST_MODELS = COUNCIL_MODELS
STOCK_CHAIRMAN_MODEL = CHAIRMAN_MODEL
CHEAP_MODEL = "google/gemini-2.5-flash"

# Dry-run mode: validate the full pipeline end-to-end for ~$0.01 before
# spending credits on the real backfill
DRY_RUN_MODELS = ["google/gemini-2.5-flash", "openai/gpt-4o-mini"]
DRY_RUN_TICKERS = ["NVDA", "TSLA"]

# Live runs may use OpenRouter web search by appending ":online" to model ids.
# Historical runs never do (point-in-time discipline).
USE_ONLINE_SEARCH = os.getenv("STOCKS_ONLINE_SEARCH", "1") not in ("0", "false")

# Strong models with web search can be slow; generous per-stage timeout
STAGE_TIMEOUT = 240.0

# Portfolio constraints: long/short, no leverage
MAX_WEIGHT_PER_NAME = 0.25   # |weight| cap per stock
MAX_GROSS = 1.0              # sum of |weights| <= 1.0, remainder is cash
FEE_BPS = 10                 # transaction cost in basis points on turnover

# Storage
STOCKS_DATA_DIR = "data/stocks"
RUNS_DIR = os.path.join(STOCKS_DATA_DIR, "runs")
PRICES_CACHE_CSV = os.path.join(STOCKS_DATA_DIR, "prices_cache.csv")
CACHE_META_JSON = os.path.join(STOCKS_DATA_DIR, "cache_meta.json")
INDEX_JSON = os.path.join(STOCKS_DATA_DIR, "index.json")

# Price cache freshness (hours) before a re-download is attempted
PRICE_CACHE_MAX_AGE_HOURS = 12

# Weekly live run scheduling (Monday 22:00 UTC, after US market close)
ENABLE_SCHEDULER = os.getenv("STOCKS_ENABLE_SCHEDULER", "1") not in ("0", "false")
