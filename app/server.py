"""HTTP API.

  uvicorn app.server:app --port 8000

  POST /retrieve  {"question": "...", "k": 30, "hops": 2}  -> top-k chunks (+ timings)
  POST /answer    {"question": "...", "k": 30, "hops": 2}  -> Claude's answer over those chunks
  GET  /health
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import DEFAULT_HOPS, TOP_K
from .pipeline import Pipeline

state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    state["pipeline"] = Pipeline()  # loads spaCy, the reranker, doc text and the degree table
    yield


app = FastAPI(title="HydraDB BEAM RAG", lifespan=lifespan)


class Query(BaseModel):
    question: str = Field(min_length=1)
    k: int = Field(TOP_K, ge=1, le=100)
    hops: int = Field(DEFAULT_HOPS, ge=1, le=2)


@app.get("/health")
def health():
    p: Pipeline = state["pipeline"]
    return {"ok": True, "documents": len(p.docs), "reranker": p.reranker.model_name,
            "device": p.reranker.device, "hubs": len(p.graph.hubs)}


# Plain `def` endpoints: FastAPI runs them in a worker thread, so the blocking
# graph and reranker calls don't stall the event loop.
@app.post("/retrieve")
def retrieve(q: Query):
    return state["pipeline"].retrieve(q.question, q.k, q.hops)


@app.post("/answer")
def answer(q: Query):
    try:  # imported lazily: /retrieve works without the anthropic package or credentials
        import anthropic

        from .answer import Answerer
    except ImportError as e:
        raise HTTPException(503, "/answer needs the anthropic package: pip install anthropic") from e

    result = state["pipeline"].retrieve(q.question, q.k, q.hops)
    if "answerer" not in state:
        try:
            state["answerer"] = Answerer()
        except anthropic.AnthropicError as e:
            raise HTTPException(503, f"Claude is not configured: {e}") from e
    try:
        out = state["answerer"].answer(q.question, result["chunks"])
    except anthropic.AuthenticationError as e:
        raise HTTPException(503, f"Anthropic credentials rejected: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise HTTPException(429, f"Anthropic rate limit: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"Anthropic API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise HTTPException(502, f"Could not reach the Anthropic API: {e}") from e
    return {**out, "retrieval": {k: v for k, v in result.items() if k != "chunks"},
            "chunks": [{k: v for k, v in c.items() if k != "text"} for c in result["chunks"]]}
