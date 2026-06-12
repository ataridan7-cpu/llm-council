# Council Capital — LLM Stock Council

A multi-LLM council deliberates on 7 stocks (**NVDA, INTC, AMD, AMZN, AAPL,
TSLA, NFLX**) using the same 3-stage engine as the chat app — parallel
analyst memos → anonymized peer ranking → chairman synthesis — and issues
machine-readable verdicts per stock: **LONG / SHORT / FLAT + conviction +
target portfolio weight**. A paper long/short portfolio rebalances to those
weights and is charted against the **S&P 500 (SPY)** and an
**equal-weight buy & hold** of the 7 stocks.

> Not investment advice. This is an experiment in multi-agent deliberation.

## Quick start

```bash
# 1. Backend deps (also installs yfinance/pandas/apscheduler)
uv sync

# 2. The dashboard lives in the nextjs-admin-dashboard repo (sibling dir)
#    First boot seeds clearly-labeled demo data so the UI isn't empty.
./start-stocks.sh

# 3. With OPENROUTER_API_KEY in .env, validate the pipeline for ~$0.01:
uv run python -m backend.stocks.council_runner --dry-run

# 4. Then run the real 12-month historical simulation (~108 strong-model
#    calls; resumable — re-run it if it stops partway):
uv run python -m backend.stocks.backfill
```

Dashboard: http://localhost:3000 · API: http://localhost:8001/api/stocks

## How performance is measured

- **Historical simulation** (12 monthly runs over the past year): each run
  is fed *only* point-in-time price data (returns, vol, drawdown — nothing
  after the simulation date; fundamentals and news are excluded because
  yfinance only serves current-state values). It is still labeled
  **hindsight-biased** in the UI: the models' training data postdates those
  dates, and no prompt can fully undo that.
- **Live forward tracking**: a scheduler runs the council weekly
  (Mon 22:00 UTC, after the US close), or press **Run council now** in the
  dashboard. Live runs may use OpenRouter web search (`:online`) and
  current fundamentals/news. This is the honest track record.

## Portfolio mechanics

- Long/short, gross exposure ≤ 100%, ≤ 25% per name, remainder in cash,
  no leverage; 10 bps transaction cost on turnover at each rebalance.
- Positions rebalance at the close of each run's date and drift until the
  next run. Verdict weights are always normalized server-side (clamping,
  gross scaling, stance/sign consistency), so malformed model output can
  never corrupt the portfolio.
- Equity curves are recomputed on read from stored verdicts + the price
  cache; there is no mutable portfolio state to corrupt.

## Model tiers

| Role | Models |
|---|---|
| Analysts + peer ranking | `COUNCIL_MODELS` (gpt-5.1, gemini-3-pro, claude-sonnet-4.5, grok-4) |
| Chairman | `CHAIRMAN_MODEL` (gemini-3-pro) |
| Parsing rescue / cheap tasks | `google/gemini-2.5-flash` |
| Dry-run mode | 2 cheap models × 2 tickers (~$0.01) |

Configure in `backend/stocks/config.py`. Env flags: `STOCKS_ONLINE_SEARCH=0`
disables web search; `STOCKS_ENABLE_SCHEDULER=0` disables the weekly cron.

## Module map (`backend/stocks/`)

| File | Purpose |
|---|---|
| `data.py` | Batched yfinance price cache; strict point-in-time snapshots |
| `prompts.py` | Stage 1/2/3 prompt builders (stage 2 keeps the chat app's `FINAL RANKING:` contract) |
| `council_runner.py` | 3-stage runner, JSON parse ladder + cheap-model rescue, weight normalization |
| `portfolio.py` | Long/short backtest vs SPY + equal-weight benchmarks |
| `backfill.py` | Resumable 12-month historical sim (CLI + API) |
| `scheduler.py` | Weekly live run via APScheduler |
| `routes.py` | `/api/stocks/*` endpoints |
| `seed_demo.py` | Heuristic demo data (labeled `demo`) for keyless boot |
| `tests/` | Portfolio math, parsing ladder, PIT discipline, mocked E2E |

Run tests: `uv run pytest`
