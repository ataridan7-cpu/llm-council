# CLAUDE.md - Technical Notes for LLM Council

This file contains technical details, architectural decisions, and important implementation notes for future development sessions.

## Project Overview

LLM Council is a 3-stage deliberation system where multiple LLMs collaboratively answer user questions. The key innovation is anonymized peer review in Stage 2, preventing models from playing favorites.

## Architecture

### Backend Structure (`backend/`)

**`config.py`**
- Contains `COUNCIL_MODELS` (list of OpenRouter model identifiers)
- Contains `CHAIRMAN_MODEL` (model that synthesizes final answer)
- Uses environment variable `OPENROUTER_API_KEY` from `.env`
- Backend runs on **port 8001** (NOT 8000 - user had another app on 8000)

**`openrouter.py`**
- `query_model()`: Single async model query
- `query_models_parallel()`: Parallel queries using `asyncio.gather()`
- Returns dict with 'content' and optional 'reasoning_details'
- Graceful degradation: returns None on failure, continues with successful responses

**`council.py`** - The Core Logic
- `stage1_collect_responses()`: Parallel queries to all council models
- `stage2_collect_rankings()`:
  - Anonymizes responses as "Response A, B, C, etc."
  - Creates `label_to_model` mapping for de-anonymization
  - Prompts models to evaluate and rank (with strict format requirements)
  - Returns tuple: (rankings_list, label_to_model_dict)
  - Each ranking includes both raw text and `parsed_ranking` list
- `stage3_synthesize_final()`: Chairman synthesizes from all responses + rankings
- `parse_ranking_from_text()`: Extracts "FINAL RANKING:" section, handles both numbered lists and plain format
- `calculate_aggregate_rankings()`: Computes average rank position across all peer evaluations

**`storage.py`**
- JSON-based conversation storage in `data/conversations/`
- Each conversation: `{id, created_at, messages[]}`
- Assistant messages contain: `{role, stage1, stage2, stage3}`
- Note: metadata (label_to_model, aggregate_rankings) is NOT persisted to storage, only returned via API

**`main.py`**
- FastAPI app with CORS enabled for localhost:5173 and localhost:3000
- POST `/api/conversations/{id}/message` returns metadata in addition to stages
- Metadata includes: label_to_model mapping and aggregate_rankings

### Frontend Structure (`frontend/src/`)

**`App.jsx`**
- Main orchestration: manages conversations list and current conversation
- Handles message sending and metadata storage
- Important: metadata is stored in the UI state for display but not persisted to backend JSON

**`components/ChatInterface.jsx`**
- Multiline textarea (3 rows, resizable)
- Enter to send, Shift+Enter for new line
- User messages wrapped in markdown-content class for padding

**`components/Stage1.jsx`**
- Tab view of individual model responses
- ReactMarkdown rendering with markdown-content wrapper

**`components/Stage2.jsx`**
- **Critical Feature**: Tab view showing RAW evaluation text from each model
- De-anonymization happens CLIENT-SIDE for display (models receive anonymous labels)
- Shows "Extracted Ranking" below each evaluation so users can validate parsing
- Aggregate rankings shown with average position and vote count
- Explanatory text clarifies that boldface model names are for readability only

**`components/Stage3.jsx`**
- Final synthesized answer from chairman
- Green-tinted background (#f0fff0) to highlight conclusion

**Styling (`*.css`)**
- Light mode theme (not dark mode)
- Primary color: #4a90e2 (blue)
- Global markdown styling in `index.css` with `.markdown-content` class
- 12px padding on all markdown content to prevent cluttered appearance

## Key Design Decisions

### Stage 2 Prompt Format
The Stage 2 prompt is very specific to ensure parseable output:
```
1. Evaluate each response individually first
2. Provide "FINAL RANKING:" header
3. Numbered list format: "1. Response C", "2. Response A", etc.
4. No additional text after ranking section
```

This strict format allows reliable parsing while still getting thoughtful evaluations.

### De-anonymization Strategy
- Models receive: "Response A", "Response B", etc.
- Backend creates mapping: `{"Response A": "openai/gpt-5.1", ...}`
- Frontend displays model names in **bold** for readability
- Users see explanation that original evaluation used anonymous labels
- This prevents bias while maintaining transparency

### Error Handling Philosophy
- Continue with successful responses if some models fail (graceful degradation)
- Never fail the entire request due to single model failure
- Log errors but don't expose to user unless all models fail

### UI/UX Transparency
- All raw outputs are inspectable via tabs
- Parsed rankings shown below raw text for validation
- Users can verify system's interpretation of model outputs
- This builds trust and allows debugging of edge cases

## Important Implementation Details

### Relative Imports
All backend modules use relative imports (e.g., `from .config import ...`) not absolute imports. This is critical for Python's module system to work correctly when running as `python -m backend.main`.

### Port Configuration
- Backend: 8001 (changed from 8000 to avoid conflict)
- Frontend: 5173 (Vite default)
- Update both `backend/main.py` and `frontend/src/api.js` if changing

### Markdown Rendering
All ReactMarkdown components must be wrapped in `<div className="markdown-content">` for proper spacing. This class is defined globally in `index.css`.

### Model Configuration
Models are hardcoded in `backend/config.py`. Chairman can be same or different from council members. The current default is Gemini as chairman per user preference.

## Common Gotchas

1. **Module Import Errors**: Always run backend as `python -m backend.main` from project root, not from backend directory
2. **CORS Issues**: Frontend must match allowed origins in `main.py` CORS middleware
3. **Ranking Parse Failures**: If models don't follow format, fallback regex extracts any "Response X" patterns in order
4. **Missing Metadata**: Metadata is ephemeral (not persisted), only available in API responses

## Stock Analysis Modules (new)

**`backend/market_data.py`**
- Cached yfinance wrappers: `get_quote`, `get_price_history`, `get_fundamentals`, `get_news`, `get_close_on_or_after`
- Pure-python indicators: `compute_indicators` (SMA 20/50/200, RSI14, 52w hi/lo, returns)
- TTL file cache under `data/cache/market/`; stale fallback on network failure

**`backend/edgar.py`**
- SEC EDGAR free API: fetch recent 10-K/10-Q/8-K for any ticker
- Requires `SEC_USER_AGENT` env var (contact info per SEC policy)
- `get_recent_filings(ticker)` → injected into fundamentals + news research prompts

**`backend/research.py`** — Stage 0
- `gather_market_data(ticker)` fetches all market data in parallel (raises ValueError on bad ticker)
- `build_dossier(ticker, data)` runs 3 specialist agents concurrently (fundamentals/technical/news)
- Each agent gets role-specific data slice; ~800-word report cap; no buy/hold/sell

**`backend/verdict.py`**
- `StockVerdict` pydantic model (verdict, confidence 0-100, price_targets{1w/1m/3m}, thesis, risks)
- `extract_verdict_json(text)` — fenced-block → balanced-brace fallback
- `parse_or_repair_verdict(text)` — one cheap-model repair call before giving up

**`backend/analysis.py`** — Finance council pipeline
- `run_stock_analysis(ticker)` — full Stage 0→1→2→3 pipeline + persistence
- Reuses `stage2_collect_rankings` and `calculate_aggregate_rankings` from `council.py` verbatim
- Stage 1 prompt: dossier + current price + `VERDICT_JSON_INSTRUCTIONS`

**`backend/scorecard.py`**
- `record_prediction(analysis)` — logs price-at-prediction + SPY baseline
- `evaluate_due_predictions()` — idempotent; fetches actual + SPY prices; computes alpha
- `compute_leaderboard()` — direction/verdict hit rates + avg alpha vs SPY for council

**`backend/watchlist.py`**
- `refresh_watchlist()` — live quotes + alerts for all 7 tickers, zero LLM calls
- Alerts: big day moves (≥5%), stale analysis (≥30d), prediction coming due, price in target range

**`backend/edgar.py`**
- Free SEC EDGAR filings injected into fundamentals + news agent prompts

### Tracked Universe
```python
TRACKED_TICKERS = ["NVDA", "INTC", "AMD", "AMZN", "AAPL", "TSLA", "NFLX"]
BENCHMARK_TICKER = "SPY"  # S&P 500 comparison
```
All analysis endpoints validate against this list.

### New API Endpoints
- `GET /api/tickers` — tracked universe
- `POST /api/analyses` / `POST /api/analyses/stream` — run analysis (SSE)
- `POST /api/analyses/bootstrap` — run all missing tickers sequentially (SSE)
- `GET /api/analyses?ticker=` / `GET /api/analyses/{id}`
- `GET /api/stocks/{ticker}/history` / `GET /api/stocks/{ticker}/overview`
- `GET /api/watchlist` — live quotes + alerts
- `GET /api/scorecard` / `POST /api/scorecard/evaluate`
- `GET /api/predictions?ticker=&status=&full=`

### Frontend Routes
- `/` — Dashboard (7-ticker grid, live prices, alerts, bootstrap button)
- `/stock/:ticker` — StockPage (chart, dossier, council stages, prediction history)
- `/scorecard` — Leaderboard with alpha vs S&P 500
- `/chat` — Original LLM Council chat (unchanged)

### Scheduling (APScheduler)
Set `ENABLE_SCHEDULER=true` in env. Runs:
- `evaluate_due_predictions` daily at 22:30 UTC
- `refresh_watchlist` daily at 13:35 UTC

## Testing
```bash
uv run --extra dev python -m pytest tests/ -v
```
Tests cover: `extract_verdict_json`, `StockVerdict`, `score_one`, indicator math, storage round-trips (45 tests).

## Future Enhancement Ideas

- Configurable council/chairman via UI instead of config file
- Streaming responses instead of batch loading
- Export conversations to markdown/PDF
- Custom ranking criteria (not just accuracy/insight)
- Support for reasoning models (o1, etc.) with special handling
- Multi-ticker portfolio-level signals
- Email/push alerts when predictions come due

## Testing Notes

Use `test_openrouter.py` to verify API connectivity and test different model identifiers before adding to council. The script tests both streaming and non-streaming modes.

## Data Flow Summary

```
User Query
    ↓
Stage 1: Parallel queries → [individual responses]
    ↓
Stage 2: Anonymize → Parallel ranking queries → [evaluations + parsed rankings]
    ↓
Aggregate Rankings Calculation → [sorted by avg position]
    ↓
Stage 3: Chairman synthesis with full context
    ↓
Return: {stage1, stage2, stage3, metadata}
    ↓
Frontend: Display with tabs + validation UI
```

The entire flow is async/parallel where possible to minimize latency.
