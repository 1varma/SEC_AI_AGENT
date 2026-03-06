import json
import boto3
import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from api.agents import (
    run_agent_loop, run_converse_agent_loop,
    is_anthropic_model, TOOLS, SYSTEM_PROMPT,
)
from api.cache import get_cached, set_cached, is_available as redis_available

# ─── Configuration ────────────────────────────────────────────────────────────
DEFAULT_MODEL  = "us.anthropic.claude-sonnet-4-6"
BEDROCK_REGION = "us-east-1"

SUPPORTED_MODELS = [
    {
        "id":          "us.anthropic.claude-sonnet-4-6",
        "name":        "Claude Sonnet 4.6",
        "provider":    "Anthropic",
        "description": "Balanced speed & intelligence (default)",
    },
    {
        "id":          "anthropic.claude-opus-4-6-v1",
        "name":        "Claude Opus 4.6",
        "provider":    "Anthropic",
        "description": "Most capable, deepest reasoning",
    },
    {
        "id":          "anthropic.claude-haiku-4-5-20251001-v1:0",
        "name":        "Claude Haiku 4.5",
        "provider":    "Anthropic",
        "description": "Fastest, most cost-efficient",
    },
    {
        "id":          "amazon.nova-2-lite-v1:0",
        "name":        "Nova 2 Lite",
        "provider":    "Amazon",
        "description": "Amazon's lightweight frontier model",
    },
    {
        "id":          "google.gemma-3-27b-it",
        "name":        "Gemma 3 27B",
        "provider":    "Google",
        "description": "Google open-weight instruction model",
    },
]

app = FastAPI(
    title="FinSight AI",
    description="Bloomberg-grade financial intelligence powered by SEC filings, stock data, and news",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Clients (initialized once) ───────────────────────────────────────────────
_anthropic_client = None
_boto_client      = None


def get_anthropic_client():
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = anthropic.AnthropicBedrock(aws_region=BEDROCK_REGION)
    return _anthropic_client


def get_boto_client():
    global _boto_client
    if _boto_client is None:
        _boto_client = boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)
    return _boto_client


# ─── Request / Response Models ────────────────────────────────────────────────
class HistoryMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query:    str
    stream:   bool = True
    history:  list[HistoryMessage] = []
    model_id: str = DEFAULT_MODEL


# ─── Endpoints ────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model":  DEFAULT_MODEL,
        "cache":  "redis" if redis_available() else "disabled",
    }


@app.get("/api/models")
def list_models():
    return {"models": SUPPORTED_MODELS}


@app.post("/api/query")
async def query(req: QueryRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    model   = req.model_id or DEFAULT_MODEL
    use_sdk = is_anthropic_model(model)
    history = [{"role": m.role, "content": m.content} for m in req.history]

    async def event_stream():
        try:
            # ── Cache check ───────────────────────────────────────────────────
            cached = get_cached(req.query)
            if cached:
                yield f"data: {json.dumps({'type': 'text',    'content': cached['answer']})}\n\n"
                yield f"data: {json.dumps({'type': 'sources', 'data': cached['sources']}, default=str)}\n\n"
                yield f"data: {json.dumps({'type': 'cached',  'value': True})}\n\n"
                yield f"data: {json.dumps({'type': 'done'})}\n\n"
                return

            full_answer = ""

            # ── Anthropic SDK path ────────────────────────────────────────────
            if use_sdk:
                client = get_anthropic_client()

                # Phase 1: tool loop
                messages, sources, _ = run_agent_loop(client, model, req.query, history)

                # Phase 2: stream final answer
                with client.messages.stream(
                    model=model,
                    max_tokens=16000,
                    system=SYSTEM_PROMPT,
                    tools=TOOLS,
                    messages=messages,
                ) as stream:
                    for chunk in stream.text_stream:
                        full_answer += chunk
                        yield f"data: {json.dumps({'type': 'text', 'content': chunk})}\n\n"

            # ── Converse API path (boto3) ─────────────────────────────────────
            else:
                boto_client = get_boto_client()

                # Phase 1: tool loop
                messages, sources, _ = run_converse_agent_loop(
                    model, req.query, history, region=BEDROCK_REGION
                )

                # Phase 2: stream final answer via converse_stream
                # messages already include the completed tool turns; append a
                # fresh user "synthesize" nudge only when the last role is assistant
                # (run_converse_agent_loop appends the final assistant message)
                stream_resp = boto_client.converse_stream(
                    modelId=model,
                    messages=messages,
                    system=[{"text": SYSTEM_PROMPT}],
                )
                for event in stream_resp["stream"]:
                    if "contentBlockDelta" in event:
                        delta = event["contentBlockDelta"].get("delta", {})
                        if "text" in delta:
                            full_answer += delta["text"]
                            yield f"data: {json.dumps({'type': 'text', 'content': delta['text']})}\n\n"
                    elif "messageStop" in event:
                        break

            # ── Sources + cache ───────────────────────────────────────────────
            yield f"data: {json.dumps({'type': 'sources', 'data': sources}, default=str)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

            set_cached(req.query, {"answer": full_answer, "sources": sources})

        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/query/sync")
async def query_sync(req: QueryRequest):
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    model   = req.model_id or DEFAULT_MODEL
    history = [{"role": m.role, "content": m.content} for m in req.history]

    cached = get_cached(req.query)
    if cached:
        return {**cached, "model": model, "cached": True}

    if is_anthropic_model(model):
        client = get_anthropic_client()
        _, sources, answer = run_agent_loop(client, model, req.query, history)
    else:
        _, sources, answer = run_converse_agent_loop(
            model, req.query, history, region=BEDROCK_REGION
        )

    result = {"answer": answer, "sources": sources, "model": model, "cached": False}
    set_cached(req.query, {"answer": answer, "sources": sources})
    return result
