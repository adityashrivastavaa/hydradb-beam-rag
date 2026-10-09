# hydradb-beam-rag

> **Slides:** [demo deck (HTML)](deck/index.html) · [PDF](deck/hydradb-memory-demo.pdf)

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

# 5. Serve (API and web UI)
uvicorn app.server:app --port 8000
```

Open <http://localhost:8000/> for the web UI: ask a question (or pick one of the
20 BEAM questions), choose 1 or 2 hops, and see the matched seed entities, a
graph of the seeds and their 1-hop neighbours, per-stage timings, and the
reranked documents. Each document expands to its full turn text. **Answer with
Claude** answers over exactly those documents, and its `[n]` citations jump to
the cited document.

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
| `POST /answer` | same, plus optional `doc_ids` (answer over these documents, skipping retrieval) | Claude's answer (`claude-opus-5-5`, single call over the top-k) plus the retrieval metadata |
| `GET /questions` | | the 20 BEAM questions for this conversation |
| `GET /health` | | document count, reranker, device |
| `GET /` | | web UI |

**Verified on macOS (Apple Silicon, Python 3.12)** from a fresh clone, following
the steps above exactly: the HydraDB build took about 2.5 minutes (Rust
dependencies already in the local cargo cache; a first-ever Rust build takes
longer), `setup_python.sh` about 2 minutes, and the loader about 2 minutes.
`python -m eval.recall` then gave Recall@30 0.356, matching the table below.

Evaluate recall against the gold evidence: `python -m eval.recall` (`--hops 1`, `--k 30`).

## Demo deck

**[Open the deck (HTML)](deck/index.html)** · **[Download as PDF](deck/hydradb-memory-demo.pdf)**

[`deck/index.html`](deck/index.html) is the slide deck for this demo: what memory is, explicit vs
implicit memory, memory files vs vector stores vs graphs, HydraDB's accuracy at
scale, then the setup steps and the three demo questions. It is one offline file
(fonts and images inlined); open it in a browser and use ← → to navigate, `F`
for full screen. GitHub shows HTML as source, so download it (or clone the repo)
and open it locally; [`deck/hydradb-memory-demo.pdf`](deck/hydradb-memory-demo.pdf)
is the same deck as a PDF. To edit, change `deck/deck.template.html` and run
`python deck/build.py`.

## Configuration

| Variable | Default | |
|---|---|---|
| `RERANKER_MODEL` | `Alibaba-NLP/gte-reranker-modernbert-base` | any sentence-transformers `CrossEncoder` |
| `RERANKER_MAX_LENGTH` | `512` | tokens per (question, document) pair |
| `GRAPH_HOPS` | `2` | default for requests that omit `hops` |
| `HOP2_CAP` | `150` | documents reranked at 2 hops, best graph score first |
| `CLAUDE_MODEL` | `claude-opus-5-5` | |
| `HYDRADB_HTTP_PORT` / `HYDRADB_TOKEN` | `8443` / `local-development-token-32-bytes` | must match `start_hydradb.sh` |
| `HYDRADB_REPO` | public `hydra-db/hydradb` | installer source |
| `HYDRADB_REF` | `4a8fff0` | HydraDB commit to build; the one this app was tested against |

## How the defaults were chosen

Measured on the 19 `c_01` questions that have gold evidence documents (Apple
Silicon, MPS, reranker input capped at 512 tokens). Recall = share of a
question's gold documents found in the top k.

| Reranker over the 2-hop pool (150 docs) | Recall@10 | Recall@30 | Hit@30 | Docs/s |
|---|---|---|---|---|
| **`Alibaba-NLP/gte-reranker-modernbert-base`** (default) | **0.29** | **0.36** | 0.63 | 19 |
| `BAAI/bge-reranker-v2-m3` | 0.27 | 0.35 | **0.68** | 9 |
| `cross-encoder/ettin-reranker-150m-v1` | 0.27 | 0.36 | 0.63 | 21 |
| `tomaarsen/Qwen3-Reranker-0.6B-seq-cls` | 0.04 | 0.08 | 0.37 | 5 |
| graph score alone, no reranker | 0.15 | 0.18 | 0.42 | – |

- gte-modernbert ties for the best Recall@30, has the best Recall@10, and is
  twice as fast as bge-reranker-v2-m3. The Qwen3 checkpoint scored near zero,
  most likely because it expects a prompt template this pipeline doesn't apply;
  it is not a fair read of that model.
- **The graph caps what reranking can reach.** 1 hop holds 38% of the gold
  documents (about 100 docs per question). The full 2-hop neighbourhood holds
  65%, but it is about 530 docs; after the cap of 150 by graph score, 39%
  survive. Raising `HOP2_CAP` trades latency for recall.
- **Latency** is about 8 s per query, almost all of it reranking 150 documents
  on the laptop GPU. The graph pass (spaCy, seed lookup, expansion, chunk
  lookup) takes about 75 ms.
- For reference, HydraDB's hosted retrieval returned 0.40 recall at k≈10 in
  fast mode and 0.52 at k≈14 in thinking mode on the same questions; it also
  uses dense and keyword search, which this pipeline deliberately does not.

Reproduce with `python -m eval.recall` (switch models with `RERANKER_MODEL=...`).

## Notes on the graph database

Shapes HydraDB accepts today, which explain how `app/graph.py` and `app/loader.py` are written:

- Relationship properties can't be written by the batched `UNWIND` edge form, so `RELATES` edges (which carry chunk id, timestamp, predicate and context) are written one statement per edge. Nodes and `PRESENT_IN` edges load in batches in under a second.
- The batched read `UNWIND $rows … MATCH (a {id: row.id})-[:R]->(b)` exists only for outgoing edges; incoming neighbours cost one request per node.
- Variable-length patterns need a fixed source vertex id and a direction, and `algo.SSpaths` returns shortest paths rather than a k-hop neighbourhood, so expansion is explicit hop-by-hop BFS.
- Hubs (≥ 500 edges; in `c_01` only the `user` entity) are included but never expanded, matching HydraDB production's super-node threshold.
