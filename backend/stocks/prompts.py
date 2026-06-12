"""Prompt builders for the 3-stage stock council.

Stage 2 keeps the exact "FINAL RANKING:" contract from the chat council so
backend.council.parse_ranking_from_text / calculate_aggregate_rankings can
be reused unchanged.
"""

import json
from typing import Any, Dict, List

from .config import MAX_WEIGHT_PER_NAME, MAX_GROSS


def build_stage1_prompt(
    as_of: str,
    kind: str,
    snapshots: List[Dict[str, Any]],
    live_extras: List[Dict[str, Any]] = None,
) -> str:
    tickers = [s["ticker"] for s in snapshots]
    data_block = json.dumps(snapshots, indent=2)

    if kind == "historical":
        time_frame = f"""You are operating AS OF {as_of}. This is a point-in-time simulation:
- Use ONLY the market data provided below.
- Do NOT reference any events, earnings, products, or price moves you may
  know about that happened after {as_of}.
- Reason from the price action and statistics given, as a disciplined
  analyst would have on that date."""
    else:
        time_frame = f"""Today is {as_of}. You may use web search to check recent news, earnings,
and guidance for these companies, in addition to the market data below."""

    extras_block = ""
    if live_extras:
        extras_block = f"""

Current fundamentals and recent headlines (from Yahoo Finance):
{json.dumps(live_extras, indent=2)}"""

    return f"""You are a portfolio analyst serving on an investment council. The council
runs a paper long/short portfolio over exactly these stocks: {", ".join(tickers)}.

{time_frame}

Market data (adjusted closes; returns and vol in percent):
{data_block}{extras_block}

Your task — write a concise analyst memo:
1. For EACH stock, give 2-4 sentences: your thesis, the key risk, and your
   stance lean (LONG, SHORT, or FLAT) with a conviction from 1-10.
2. Think cross-sectionally: these positions compete for capital in one
   portfolio (gross exposure capped at {int(MAX_GROSS * 100)}%, max {int(MAX_WEIGHT_PER_NAME * 100)}% per name,
   shorts allowed, remainder in cash).
3. End with a summary line per stock: TICKER — STANCE — conviction/10 —
   suggested weight (signed percent, negative = short).

Be specific and evidence-driven. Do not hedge every position to FLAT; take
positions where the data supports them."""


def build_stage2_prompt(as_of: str, responses_text: str) -> str:
    return f"""You are evaluating anonymized analyst memos written for an investment
council as of {as_of}. The council runs a paper long/short portfolio.

Here are the memos (anonymized):

{responses_text}

Your task:
1. First, evaluate each memo individually on: evidence discipline (claims
   grounded in the data provided), risk awareness, internal consistency
   (stance and conviction follow from the stated thesis), and decisiveness.
2. Then, at the very end of your response, provide a final ranking.

IMPORTANT: Your final ranking MUST be formatted EXACTLY as follows:
- Start with the line "FINAL RANKING:" (all caps, with colon)
- Then list the responses from best to worst as a numbered list
- Each line should be: number, period, space, then ONLY the response label (e.g., "1. Response A")
- Do not add any other text or explanations in the ranking section

Example of the correct format for the END of your response:

FINAL RANKING:
1. Response C
2. Response A
3. Response B

Now provide your evaluation and ranking:"""


def build_stage3_prompt(
    as_of: str,
    kind: str,
    tickers: List[str],
    stage1_text: str,
    stage2_text: str,
    aggregate_text: str,
) -> str:
    verdict_fields = (
        '{"ticker": "NVDA", "stance": "LONG|SHORT|FLAT", "conviction": 1-10, '
        '"target_weight": signed decimal, "rationale": "<= 40 words"}'
    )
    return f"""You are the Chairman of an investment council deliberating as of {as_of}.
Analyst memos and anonymous peer rankings are below. Synthesize them into
the council's final positioning for a paper long/short portfolio over
exactly these stocks: {", ".join(tickers)}.

ANALYST MEMOS:
{stage1_text}

PEER RANKINGS (of anonymized memos):
{stage2_text}

AGGREGATE PEER RANKING (lower = better):
{aggregate_text}

Weigh higher-ranked analysts' views more heavily, but exercise your own
judgment where the council disagrees.

Write a brief synthesis (the council's market view, key disagreements, and
how you resolved them), then END your response with a single fenced JSON
code block, exactly this shape, with one object per stock ({len(tickers)} total):

```json
{{"verdicts": [{verdict_fields}, ...]}}
```

Hard constraints on the JSON:
- stance: "LONG", "SHORT", or "FLAT" only
- conviction: integer 1-10
- target_weight: decimal fraction of the portfolio, e.g. 0.15 = 15% long,
  -0.10 = 10% short; FLAT means exactly 0
- |target_weight| <= {MAX_WEIGHT_PER_NAME} per stock; sum of |target_weight| <= {MAX_GROSS}
  (the remainder is cash)
- The JSON block must be the LAST thing in your response, with no text after it."""


def build_rescue_prompt(raw_text: str, tickers: List[str]) -> str:
    return f"""Extract the stock verdicts from the analyst text below into JSON.

Output ONLY a JSON object of exactly this shape, one entry per ticker for
ALL of these tickers: {", ".join(tickers)}.

{{"verdicts": [{{"ticker": "...", "stance": "LONG|SHORT|FLAT", "conviction": 1-10, "target_weight": signed decimal, "rationale": "..."}}]}}

If the text gives no clear verdict for a ticker, use stance "FLAT",
conviction 5, target_weight 0. Do not add any text outside the JSON.

TEXT:
{raw_text}"""
