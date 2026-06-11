"""FastAPI backend for LLM Council."""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uuid
import json
import asyncio

from . import storage
from .council import run_full_council, generate_conversation_title, stage1_collect_responses, stage2_collect_rankings, stage3_synthesize_final, calculate_aggregate_rankings
from .analysis import run_stock_analysis, stage1_collect_verdicts, stage3_chairman_report, build_analysis_question
from .market_data import get_price_history
from .research import build_dossier, gather_market_data
from .scorecard import evaluate_due_predictions, compute_leaderboard, record_prediction, enrich_prediction_with_spy
from .config import TRACKED_TICKERS

app = FastAPI(title="LLM Council API")

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""
    pass


class SendMessageRequest(BaseModel):
    """Request to send a message in a conversation."""
    content: str


class ConversationMetadata(BaseModel):
    """Conversation metadata for list view."""
    id: str
    created_at: str
    title: str
    message_count: int


class Conversation(BaseModel):
    """Full conversation with all messages."""
    id: str
    created_at: str
    title: str
    messages: List[Dict[str, Any]]


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"status": "ok", "service": "LLM Council API"}


@app.get("/api/conversations", response_model=List[ConversationMetadata])
async def list_conversations():
    """List all conversations (metadata only)."""
    return storage.list_conversations()


@app.post("/api/conversations", response_model=Conversation)
async def create_conversation(request: CreateConversationRequest):
    """Create a new conversation."""
    conversation_id = str(uuid.uuid4())
    conversation = storage.create_conversation(conversation_id)
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(conversation_id: str):
    """Get a specific conversation with all its messages."""
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


@app.post("/api/conversations/{conversation_id}/message")
async def send_message(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and run the 3-stage council process.
    Returns the complete response with all stages.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    # Add user message
    storage.add_user_message(conversation_id, request.content)

    # If this is the first message, generate a title
    if is_first_message:
        title = await generate_conversation_title(request.content)
        storage.update_conversation_title(conversation_id, title)

    # Run the 3-stage council process
    stage1_results, stage2_results, stage3_result, metadata = await run_full_council(
        request.content
    )

    # Add assistant message with all stages
    storage.add_assistant_message(
        conversation_id,
        stage1_results,
        stage2_results,
        stage3_result
    )

    # Return the complete response with metadata
    return {
        "stage1": stage1_results,
        "stage2": stage2_results,
        "stage3": stage3_result,
        "metadata": metadata
    }


@app.post("/api/conversations/{conversation_id}/message/stream")
async def send_message_stream(conversation_id: str, request: SendMessageRequest):
    """
    Send a message and stream the 3-stage council process.
    Returns Server-Sent Events as each stage completes.
    """
    # Check if conversation exists
    conversation = storage.get_conversation(conversation_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Check if this is the first message
    is_first_message = len(conversation["messages"]) == 0

    async def event_generator():
        try:
            # Add user message
            storage.add_user_message(conversation_id, request.content)

            # Start title generation in parallel (don't await yet)
            title_task = None
            if is_first_message:
                title_task = asyncio.create_task(generate_conversation_title(request.content))

            # Stage 1: Collect responses
            yield f"data: {json.dumps({'type': 'stage1_start'})}\n\n"
            stage1_results = await stage1_collect_responses(request.content)
            yield f"data: {json.dumps({'type': 'stage1_complete', 'data': stage1_results})}\n\n"

            # Stage 2: Collect rankings
            yield f"data: {json.dumps({'type': 'stage2_start'})}\n\n"
            stage2_results, label_to_model = await stage2_collect_rankings(request.content, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield f"data: {json.dumps({'type': 'stage2_complete', 'data': stage2_results, 'metadata': {'label_to_model': label_to_model, 'aggregate_rankings': aggregate_rankings}})}\n\n"

            # Stage 3: Synthesize final answer
            yield f"data: {json.dumps({'type': 'stage3_start'})}\n\n"
            stage3_result = await stage3_synthesize_final(request.content, stage1_results, stage2_results)
            yield f"data: {json.dumps({'type': 'stage3_complete', 'data': stage3_result})}\n\n"

            # Wait for title generation if it was started
            if title_task:
                title = await title_task
                storage.update_conversation_title(conversation_id, title)
                yield f"data: {json.dumps({'type': 'title_complete', 'data': {'title': title}})}\n\n"

            # Save complete assistant message
            storage.add_assistant_message(
                conversation_id,
                stage1_results,
                stage2_results,
                stage3_result
            )

            # Send completion event
            yield f"data: {json.dumps({'type': 'complete'})}\n\n"

        except Exception as e:
            # Send error event
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


# ---------------------------------------------------------------------------
# Stock analysis endpoints
# ---------------------------------------------------------------------------

class AnalysisRequest(BaseModel):
    ticker: str


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data)}\n\n"


@app.get("/api/tickers")
async def list_tracked_tickers():
    """Return the fixed list of tracked tickers."""
    return {"tickers": TRACKED_TICKERS}


def _validate_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    if t not in TRACKED_TICKERS:
        raise HTTPException(
            status_code=400,
            detail=f"'{t}' is not in the tracked universe. Supported tickers: {', '.join(TRACKED_TICKERS)}"
        )
    return t


@app.post("/api/analyses")
async def create_analysis(request: AnalysisRequest):
    """Run a full stock analysis (blocking). Returns 400 for out-of-universe tickers."""
    ticker = _validate_ticker(request.ticker)
    try:
        analysis = await run_stock_analysis(ticker)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return analysis


@app.post("/api/analyses/stream")
async def create_analysis_stream(request: AnalysisRequest):
    """Run a full stock analysis, streaming progress as SSE events."""
    ticker = _validate_ticker(request.ticker)

    async def event_generator():
        try:
            yield _sse({"type": "analysis_start", "ticker": ticker})

            # Fetch market data
            try:
                data = await gather_market_data(ticker)
            except ValueError as e:
                yield _sse({"type": "error", "message": str(e)})
                return

            quote = data["quote"]
            yield _sse({"type": "data_fetch_complete", "data": {"quote": quote}})

            # Stage 0: research dossier
            yield _sse({"type": "stage0_start"})
            from .research import run_research_agent
            from .config import RESEARCH_MODELS

            # Run research agents, yielding each as it completes
            sections = []
            agent_tasks = {
                role: asyncio.create_task(run_research_agent(role, ticker, data))
                for role in RESEARCH_MODELS
            }
            pending = set(agent_tasks.values())
            while pending:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    result = task.result()
                    if result:
                        sections.append(result)
                        yield _sse({"type": "stage0_agent_complete", "data": {
                            "role": result["role"],
                            "title": result["title"],
                            "model": result["model"],
                            "report": result["report"],
                        }})

            dossier_text = "\n\n---\n\n".join(
                f"# {s['title']} Report\n\n{s['report']}" for s in sections
            )
            dossier = {
                "sections": sections,
                "data_used": {
                    "quote": quote,
                    "indicators": data["indicators"],
                    "news_count": len(data["news"]),
                },
                "dossier_text": dossier_text,
            }
            yield _sse({"type": "stage0_complete", "data": {
                "sections": [{"role": s["role"], "title": s["title"]} for s in sections]
            }})

            question = build_analysis_question(ticker, quote)

            # Stage 1
            yield _sse({"type": "stage1_start"})
            stage1_results = await stage1_collect_verdicts(ticker, quote, dossier_text)
            yield _sse({"type": "stage1_complete", "data": stage1_results})

            # Stage 2
            yield _sse({"type": "stage2_start"})
            stage2_results, label_to_model = await stage2_collect_rankings(question, stage1_results)
            aggregate_rankings = calculate_aggregate_rankings(stage2_results, label_to_model)
            yield _sse({"type": "stage2_complete", "data": stage2_results,
                        "metadata": {"label_to_model": label_to_model, "aggregate_rankings": aggregate_rankings}})

            # Stage 3
            yield _sse({"type": "stage3_start"})
            stage3_result = await stage3_chairman_report(
                ticker, quote, dossier_text, stage1_results, stage2_results
            )
            yield _sse({"type": "stage3_complete", "data": stage3_result})

            # Persist
            import uuid as _uuid
            analysis_id = str(_uuid.uuid4())
            metadata = {"label_to_model": label_to_model, "aggregate_rankings": aggregate_rankings}
            analysis = {
                "id": analysis_id,
                "ticker": ticker,
                "created_at": __import__("datetime").datetime.utcnow().isoformat(),
                "question": question,
                "market_snapshot": quote,
                "dossier": dossier,
                "stage1": stage1_results,
                "stage2": stage2_results,
                "stage3": stage3_result,
                "metadata": metadata,
                "prediction_id": None,
            }
            storage.save_analysis(analysis)
            prediction = record_prediction(analysis)
            await enrich_prediction_with_spy(prediction)
            analysis["prediction_id"] = prediction["id"]
            storage.save_analysis(analysis)

            yield _sse({"type": "prediction_recorded", "data": {"prediction_id": prediction["id"]}})
            yield _sse({"type": "complete", "data": {"analysis_id": analysis_id}})

        except Exception as e:
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
    )


@app.get("/api/analyses")
async def list_analyses(ticker: Optional[str] = Query(default=None)):
    return storage.list_analyses(ticker=ticker)


@app.get("/api/analyses/{analysis_id}")
async def get_analysis(analysis_id: str):
    analysis = storage.get_analysis(analysis_id)
    if analysis is None:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@app.get("/api/stocks/{ticker}/history")
async def stock_history(
    ticker: str,
    period: str = Query(default="1y"),
    interval: str = Query(default="1d"),
):
    history = await get_price_history(ticker, period=period, interval=interval)
    if history is None:
        raise HTTPException(status_code=404, detail=f"No price history for {ticker}")
    return history


@app.get("/api/stocks/{ticker}/overview")
async def stock_overview(ticker: str):
    from .market_data import get_quote
    ticker = _validate_ticker(ticker)
    quote = await get_quote(ticker)
    if quote is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {ticker}")
    analyses = storage.list_analyses(ticker=ticker)
    latest_analysis = analyses[0] if analyses else None
    predictions = storage.list_predictions(ticker=ticker)
    return {
        "quote": quote,
        "latest_analysis": latest_analysis,
        "predictions": predictions[:10],
    }


# ---------------------------------------------------------------------------
# Scorecard endpoints
# ---------------------------------------------------------------------------

@app.get("/api/scorecard")
async def get_scorecard():
    return compute_leaderboard()


@app.post("/api/scorecard/evaluate")
async def trigger_evaluate():
    result = await evaluate_due_predictions()
    return result


@app.get("/api/predictions")
async def list_predictions_endpoint(
    ticker: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
):
    return storage.list_predictions(ticker=ticker, status=status)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
