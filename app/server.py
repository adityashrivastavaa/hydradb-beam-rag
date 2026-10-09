"""HTTP API.

  uvicorn app.server:app --port 8000

  POST /retrieve  {"question": "...", "k": 30, "hops": 2}  -> top-k chunks (+ timings)
  POST /answer    {"question": "...", "k": 30, "hops": 2}  -> Claude's answer over those chunks
  GET  /questions  -> the BEAM questions for this conversation
  GET  /health
  GET  /         -> web UI (app/static/index.html)
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import DATA_DIR, DEFAULT_HOPS, TOP_K
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


INDEX = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(INDEX)


@app.get("/questions")
def questions():
    """The BEAM probing questions for this conversation, as examples for the UI."""
    qs = json.loads((DATA_DIR / "questions.json").read_text())
    return [{"category": q["category"], "question": q["question"], "has_gold": bool(q["gold_doc_ids"])}
            for q in qs]


class AnswerQuery(Query):
    # Pass the doc ids from an earlier /retrieve (in rank order) to answer over exactly
    # those, without repeating retrieval.
    doc_ids: list[str] | None = None


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
def answer(q: AnswerQuery):
    try:  # imported lazily: /retrieve works without the anthropic package or credentials
        import anthropic

        from .answer import Answerer
    except ImportError as e:
        raise HTTPException(503, "/answer needs the anthropic package: pip install anthropic") from e

    p: Pipeline = state["pipeline"]
    if q.doc_ids:
        unknown = [d for d in q.doc_ids if d not in p.docs]
        if unknown:
            raise HTTPException(400, f"unknown doc_ids: {unknown[:5]}")
        result = {"question": q.question, "chunks": [{"rank": i, "doc_id": d, "text": p.docs[d]}
                                                     for i, d in enumerate(q.doc_ids[:q.k], 1)]}
    else:
        result = p.retrieve(q.question, q.k, q.hops)
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
