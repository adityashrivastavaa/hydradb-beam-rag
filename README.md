# hydradb-beam-rag

Graph-first retrieval over one BEAM-1M conversation, running entirely on your
machine:

1. **Graph pass.** spaCy pulls entity phrases from the question. They are
   matched to entity names in a local **HydraDB** graph database
   ([hydra-db/hydradb](https://github.com/hydra-db/hydradb), open source, AGPL-3.0),
   then expanded 1–2 hops over `RELATES` edges. Every
   document the neighbourhood touches through `PRESENT_IN` becomes a candidate.
2. **Rerank pass.** A local cross-encoder scores (question, document) and keeps
   the top 30.
3. **Answer (optional).** Claude answers from those 30 documents.

The bundled data is BEAM-1M conversation 1 (`c_01`): 4,852 entities, 9,227
relations, 2,283 chunks across 854 documents (one document = one conversation
turn), plus the 20 BEAM probing questions with their gold evidence documents. The data comes from
the [BEAM benchmark](https://github.com/mohammadtavakoli78/BEAM) and is licensed
CC BY-SA 4.0; see [data/beam_c01/LICENSE.md](data/beam_c01/LICENSE.md).

> **Chunks vs documents.** The graph links entities to chunk ids
> (`<doc>_chunk_NNNN`), but text is available per document, so retrieval
> returns documents. "Top 30 chunks" in the API means the top 30 documents.

## Quick start

```bash
# 1. Build the graph database (native deps listed at the top of the script)
HYDRADB_DIR=~/src/hydradb scripts/install_hydradb.sh

# 2. Start it (foreground; leave it running in its own terminal)
HYDRADB_DIR=~/src/hydradb scripts/start_hydradb.sh

# 3. Python env, spaCy model, reranker weights
scripts/setup_python.sh && source .venv/bin/activate

# 4. Load the conversation graph (~2 min; writes data/beam_c01/idmap.json)
python -m app.loader

# 5. Serve
uvicorn app.server:app --port 8000
```

```bash
curl -s localhost:8000/retrieve -H 'content-type: application/json' \
  -d '{"question": "Which port did I say my memory store was running on?", "k": 30}' | jq '.chunks[:3]'

# Needs ANTHROPIC_API_KEY (or an `ant auth login` profile)
curl -s localhost:8000/answer -H 'content-type: application/json' \
  -d '{"question": "What is the TTL value set for caching recent translations?"}' | jq .answer
```

| Endpoint | Body | Returns |
|---|---|---|
| `POST /retrieve` | `question`, `k` (default 30), `hops` (1 or 2) | ranked `chunks` (doc id, rerank score, graph score, hop, text), matched seeds, pool size, per-stage timings |
| `POST /answer` | same | Claude's answer (`claude-opus-5-5`, single call over the top-k) plus the retrieval metadata |
| `GET /health` | | document count, reranker, device |

Evaluate recall against the gold evidence: `python -m eval.recall` (`--hops 1`, `--k 30`).

## Configuration

| Variable | Default | |
|---|---|---|
| `RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | any sentence-transformers `CrossEncoder` |
| `RERANKER_MAX_LENGTH` | `512` | tokens per (question, document) pair |
| `GRAPH_HOPS` | `2` | default for requests that omit `hops` |
| `HOP2_CAP` | `150` | documents reranked at 2 hops, best graph score first |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `HYDRADB_HTTP_PORT` / `HYDRADB_TOKEN` | `8443` / `local-development-token-32-bytes` | must match `start_hydradb.sh` |
| `HYDRADB_REPO` | public `hydra-db/hydradb` | installer source |

## How the defaults were chosen

RESULTS_PLACEHOLDER

## Notes on the graph database

Shapes HydraDB accepts today, which explain how `app/graph.py` and `app/loader.py` are written:

- Relationship properties can't be written by the batched `UNWIND` edge form, so `RELATES` edges (which carry chunk id, timestamp, predicate and context) are written one statement per edge. Nodes and `PRESENT_IN` edges load in batches in under a second.
- The batched read `UNWIND $rows … MATCH (a {id: row.id})-[:R]->(b)` exists only for outgoing edges; incoming neighbours cost one request per node.
- Variable-length patterns need a fixed source vertex id and a direction, and `algo.SSpaths` returns shortest paths rather than a k-hop neighbourhood, so expansion is explicit hop-by-hop BFS.
- Hubs (≥ 500 edges; in `c_01` only the `user` entity) are included but never expanded, matching HydraDB production's super-node threshold.
