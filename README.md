# Stock Council — LLM Investment Committee

A multi-stage LLM deliberation system that researches and debates investments in 7 tech stocks, tracks its own predictions, and scores results against the S&P 500.

## How It Works

For each stock analysis:

1. **Stage 0 — Research Dossier**: Three specialist AI agents (fundamentals, technical, news/sentiment) each receive real market data (yfinance + SEC EDGAR filings) and write their section of a research report.
2. **Stage 1 — Council Opinions**: Four frontier LLMs each read the dossier and produce a structured verdict (buy/hold/sell, confidence %, price targets for 1w/1m/3m).
3. **Stage 2 — Peer Review**: Models rank each other's responses anonymously (preventing favoritism).
4. **Stage 3 — Chairman Synthesis**: The chairman model writes the final investment report and issues the council's official verdict.

Every verdict is logged. After the target windows pass, actual prices are fetched and each prediction is scored — including alpha vs S&P 500 (SPY).

## Tracked Tickers

NVDA · INTC · AMD · AMZN · AAPL · TSLA · NFLX

## Setup

### 1. Install dependencies

```bash
uv sync
cd frontend && npm install && cd ..
```

### 2. Configure `.env`

```bash
OPENROUTER_API_KEY=sk-or-v1-...

# Optional
SEC_USER_AGENT=your-app contact@example.com
ALPHA_VANTAGE_API_KEY=...
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
ENABLE_SCHEDULER=false        # set true for daily auto-evaluation
WATCHLIST_QUICK_SIGNAL=false  # set true for cheap per-ticker signals on refresh
```

### 3. Run

```bash
# Both servers at once
./start.sh

# Or manually
uv run python -m backend.main   # backend on :8001
cd frontend && npm run dev       # frontend on :5173
```

### 4. Bootstrap (first run)

Open http://localhost:5173 — the Dashboard shows all 7 tickers. Click **Run All Analyses** to run the full council on every ticker. This takes several minutes (one analysis at a time, each requires ~10–15 LLM calls).

### 5. Evaluate predictions

After 1 week / 1 month / 3 months, go to the **Scorecard** page and click **Evaluate Now**. Actual prices and SPY benchmark returns are fetched automatically.

### 6. Run tests

```bash
uv run --extra dev python -m pytest tests/ -v
```

## Architecture

```
Dashboard (7 tickers, live prices, alerts)
    ↓ click ticker
StockPage (price chart, dossier, council stages, prediction history)
    ↓ "Run Council Analysis"
Stage 0: research agents (gemini-flash / gpt-mini, cheap)
    ↓
Stage 1: council verdicts (frontier models, structured JSON)
    ↓
Stage 2: anonymized peer ranking (existing council machinery)
    ↓
Stage 3: chairman synthesis + final verdict
    ↓
data/analyses/{id}.json + data/predictions/{id}.json
    ↓
Scorecard: hit rates per model + alpha vs S&P 500
```

## Tech Stack

- **Backend**: FastAPI, Python 3.10+, httpx, yfinance, APScheduler, feedparser
- **Frontend**: React 19, Vite, react-router-dom, lightweight-charts, react-markdown
- **Data**: JSON files (`data/analyses/`, `data/predictions/`, `data/cache/`)
- **LLMs**: OpenRouter (multi-provider: OpenAI, Google, Anthropic, xAI)

> **Disclaimer**: For research and educational purposes only. Not financial advice.
