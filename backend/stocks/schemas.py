"""Pydantic schemas for stock council runs and verdicts."""

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


Stance = Literal["LONG", "SHORT", "FLAT"]
RunKind = Literal["historical", "live", "dry_run", "demo"]
RunStatus = Literal["running", "complete", "failed"]


class StockVerdict(BaseModel):
    """The council's final position on a single stock."""

    ticker: str
    stance: Stance
    conviction: int = Field(default=5, ge=1, le=10)
    # Signed target weight: positive = long, negative = short, 0 = flat
    target_weight: float = 0.0
    rationale: str = ""


class PortfolioTarget(BaseModel):
    """Normalized portfolio allocation derived from the verdicts."""

    weights: Dict[str, float]
    cash: float
    gross: float


class CouncilRun(BaseModel):
    """A complete (or in-progress) council deliberation run."""

    run_id: str
    kind: RunKind
    as_of: str  # ISO date the run reasons "as of" (snapped to trading day)
    created_at: str
    status: RunStatus = "running"
    progress: Dict[str, str] = Field(default_factory=lambda: {"stage": "pending"})
    models: Dict[str, Any] = Field(default_factory=dict)
    tickers: List[str] = Field(default_factory=list)
    data_summary: Dict[str, Any] = Field(default_factory=dict)
    stage1: List[Dict[str, Any]] = Field(default_factory=list)
    stage2: List[Dict[str, Any]] = Field(default_factory=list)
    label_to_model: Dict[str, str] = Field(default_factory=dict)
    aggregate_rankings: List[Dict[str, Any]] = Field(default_factory=list)
    stage3: Dict[str, Any] = Field(default_factory=dict)
    verdicts: List[StockVerdict] = Field(default_factory=list)
    portfolio_target: Optional[PortfolioTarget] = None
    error: Optional[str] = None

    def stance_summary(self) -> Dict[str, str]:
        return {v.ticker: v.stance for v in self.verdicts}

    def index_entry(self) -> Dict[str, Any]:
        """Compact metadata for index.json / run-list API."""
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "as_of": self.as_of,
            "status": self.status,
            "created_at": self.created_at,
            "stance_summary": self.stance_summary(),
        }
