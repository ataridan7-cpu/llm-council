"""Structured stock verdicts: schema, extraction, and repair."""

import json
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

from .config import REPAIR_MODEL
from .openrouter import query_model


class PriceTarget(BaseModel):
    direction: Literal["up", "down", "flat"]
    low: Optional[float] = None
    high: Optional[float] = None


class StockVerdict(BaseModel):
    verdict: Literal["buy", "hold", "sell"]
    confidence: int = Field(ge=0, le=100)
    price_targets: Dict[Literal["1w", "1m", "3m"], PriceTarget]
    thesis: str
    key_risks: List[str] = []


VERDICT_JSON_INSTRUCTIONS = """
After your analysis, end your response with the heading "FINAL VERDICT:" followed by exactly one ```json fenced code block matching this schema (no text after the block):

FINAL VERDICT:
```json
{
  "verdict": "buy" | "hold" | "sell",
  "confidence": <integer 0-100>,
  "price_targets": {
    "1w": {"direction": "up" | "down" | "flat", "low": <number>, "high": <number>},
    "1m": {"direction": "up" | "down" | "flat", "low": <number>, "high": <number>},
    "3m": {"direction": "up" | "down" | "flat", "low": <number>, "high": <number>}
  },
  "thesis": "<one-paragraph summary of your core thesis>",
  "key_risks": ["<risk 1>", "<risk 2>"]
}
```

The "low" and "high" values are absolute prices in the stock's currency (not percentages), anchored to the current price."""


def _find_balanced_json(text: str) -> Optional[str]:
    """Extract the first balanced {...} object starting from the first '{'."""
    start = text.find('{')
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def extract_verdict_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract the verdict JSON object from a model response.

    Tries, in order: the last ```json fenced block, then the first balanced
    {...} after the final "FINAL VERDICT" marker, then the last balanced
    {...} anywhere in the text.
    """
    if not text:
        return None

    candidates = []

    fences = re.findall(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if fences:
        candidates.append(fences[-1])

    marker_idx = text.rfind("FINAL VERDICT")
    if marker_idx != -1:
        balanced = _find_balanced_json(text[marker_idx:])
        if balanced:
            candidates.append(balanced)

    # Last resort: try balanced {...} objects scanning backward through the text,
    # preferring one that actually contains a "verdict" key
    brace_positions = [m.start() for m in re.finditer(r'\{', text)]
    for pos in reversed(brace_positions[-20:]):
        balanced = _find_balanced_json(text[pos:])
        if balanced and '"verdict"' in balanced:
            candidates.append(balanced)
            break

    for candidate in candidates:
        try:
            parsed = json.loads(candidate.strip())
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            continue
    return None


async def parse_or_repair_verdict(text: str) -> Optional[StockVerdict]:
    """
    Parse a StockVerdict from model output, with one cheap-model repair
    attempt before giving up. Returns None on failure (graceful degradation).
    """
    raw = extract_verdict_json(text)
    if raw is not None:
        try:
            return StockVerdict.model_validate(raw)
        except ValidationError:
            pass

    if not text:
        return None

    repair_prompt = f"""Extract the investment verdict from the following analysis into JSON.
Output ONLY a JSON object with this exact shape (absolute prices, not percentages):
{{"verdict": "buy"|"hold"|"sell", "confidence": <int 0-100>, "price_targets": {{"1w": {{"direction": "up"|"down"|"flat", "low": <number or null>, "high": <number or null>}}, "1m": {{...}}, "3m": {{...}}}}, "thesis": "<one paragraph>", "key_risks": ["..."]}}

Analysis:
{text[-6000:]}"""

    response = await query_model(
        REPAIR_MODEL,
        [{"role": "user", "content": repair_prompt}],
        timeout=60.0,
        response_format={"type": "json_object"},
    )
    if response is None:
        return None
    try:
        raw = json.loads(response.get('content') or '')
        return StockVerdict.model_validate(raw)
    except (json.JSONDecodeError, ValidationError):
        return None
