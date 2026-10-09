"""First pass: question -> spaCy entities -> 1/2-hop neighbourhood in HydraDB -> documents.

Deliberately simpler than HydraDB's production thinking-mode graph lane:
  * seeds are spaCy noun chunks and named entities, lowercased and matched
    exactly against Entity.name (production matches lowercased names exactly too);
  * expansion is breadth-first over RELATES in both directions; hubs (>= 500
    edges, production's super-node threshold) are kept but never expanded;
  * every entity reached links to chunks through PRESENT_IN, and each chunk
    belongs to one source document (one BEAM turn). A document's graph score is
    sum over linked entities of 1 / 2**hop (seed 1, 1-hop 0.5, 2-hop 0.25).

HydraDB notes that shaped the queries:
  * the batched read `UNWIND $rows ... MATCH (a {id: row.id})-[:R]->(b)` exists
    only in the outgoing direction, so incoming edges are one request per node;
  * variable-length patterns must start from a fixed vertex id and cannot be
    undirected, and algo.SSpaths returns shortest paths, not a k-hop
    neighbourhood - hence explicit hop-by-hop BFS.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import spacy

from .config import DATA_DIR, HOP2_CAP, HUB_DEGREE, SUB_TENANT
from .hydradb import HydraDB

SEED_LOOKUP = "MATCH (e:Entity {name: $name, sub_tenant_id: $st}) RETURN e.id AS id"
OUT_BATCH = "UNWIND $rows AS row MATCH (a {id: row.id})-[:RELATES]->(b) RETURN row.id AS src, b.id AS dst"
IN_ONE = "MATCH (a {id: $id})<-[:RELATES]-(b:Entity) RETURN b.id AS id"
CHUNKS_BATCH = "UNWIND $rows AS row MATCH (a {id: row.id})-[:PRESENT_IN]->(b) RETURN row.id AS src, b.id AS dst"
DEG_OUT = "MATCH (e:Entity {sub_tenant_id: $st})-[:RELATES]->(o:Entity) RETURN e.id AS id, count(*) AS d"
DEG_IN = "MATCH (e:Entity {sub_tenant_id: $st}) MATCH (o:Entity)-[:RELATES]->(e) RETURN e.id AS id, count(*) AS d"

STRIP = {"the", "a", "an", "my", "our", "your", "this", "that", "these", "those", "its", "their", "his", "her"}


@dataclass
class GraphResult:
    seeds: dict[int, str] = field(default_factory=dict)        # vertex id -> matched name
    candidates: list[str] = field(default_factory=list)        # phrases tried
    hop_of: dict[int, int] = field(default_factory=dict)       # entity vertex -> hop distance
    doc_scores: dict[str, float] = field(default_factory=dict)  # doc id -> graph score
    doc_min_hop: dict[str, int] = field(default_factory=dict)
    timings_ms: dict[str, float] = field(default_factory=dict)
    requests: int = 0

    def pool(self, hops: int, cap: int | None = None) -> list[str]:
        """Documents within `hops`, best graph score first, optionally capped."""
        docs = [d for d, h in self.doc_min_hop.items() if h <= hops]
        docs.sort(key=lambda d: (-self.doc_scores[d], d))
        return docs[:cap] if cap else docs


class GraphRetriever:
    def __init__(self, tl: HydraDB | None = None, workers: int = 8):
        self.tl = tl or HydraDB()
        self.nlp = spacy.load("en_core_web_sm")
        self.pool = ThreadPoolExecutor(workers)
        idmap = json.loads((DATA_DIR / "idmap.json").read_text())
        self.chunk_of = {v: k for k, v in idmap["chunks"].items()}
        # Degree table, computed once (production caches entity degrees too).
        deg: dict[int, int] = defaultdict(int)
        for cy in (DEG_OUT, DEG_IN):
            for v, d in self.tl.query(cy, {"st": SUB_TENANT}):
                deg[v] += d
        self.hubs = {v for v, d in deg.items() if d >= HUB_DEGREE}

    # -- seeds -------------------------------------------------------------------
    def candidates(self, text: str) -> list[str]:
        doc = self.nlp(text)
        out: list[str] = []
        for span in list(doc.noun_chunks) + list(doc.ents):
            toks = [t for t in span if not t.is_punct]
            while toks and (toks[0].lower_ in STRIP or toks[0].pos_ in ("DET", "PRON")):
                toks = toks[1:]
            if not toks:
                continue
            phrase = " ".join(t.lower_ for t in toks)
            lemma = " ".join([t.lower_ for t in toks[:-1]] + [toks[-1].lemma_.lower()])
            for p in (phrase, lemma, toks[-1].lower_ if len(toks) > 1 else None):
                if p and len(p) >= 3 and p not in out:
                    out.append(p)
        return out

    # -- traversal ---------------------------------------------------------------
    def _q(self, res: GraphResult, cypher: str, params: dict):
        res.requests += 1
        return self.tl.query(cypher, params)

    def _neighbours(self, res: GraphResult, frontier: list[int]) -> dict[int, set[int]]:
        nb: dict[int, set[int]] = defaultdict(set)
        rows = [{"id": v} for v in frontier]
        outs = [self.pool.submit(self._q, res, OUT_BATCH, {"rows": rows[i:i + 1000]})
                for i in range(0, len(rows), 1000)]
        ins = {v: self.pool.submit(self._q, res, IN_ONE, {"id": v}) for v in frontier}
        for f in outs:
            for s, d in f.result():
                nb[s].add(d)
        for v, f in ins.items():
            nb[v].update(r[0] for r in f.result())
        return nb

    def retrieve(self, question: str, hops: int = 2) -> GraphResult:
        res = GraphResult()
        t0 = time.perf_counter()
        res.candidates = self.candidates(question)
        res.timings_ms["spacy"] = (time.perf_counter() - t0) * 1e3

        t0 = time.perf_counter()
        looked = self.pool.map(lambda n: (n, self._q(res, SEED_LOOKUP, {"name": n, "st": SUB_TENANT})),
                               res.candidates)
        res.seeds = {r[0]: n for n, rows in looked for r in rows}
        res.timings_ms["seed_lookup"] = (time.perf_counter() - t0) * 1e3
        if not res.seeds:
            return res

        t0 = time.perf_counter()
        res.hop_of = {v: 0 for v in res.seeds}
        frontier = set(res.seeds) - self.hubs
        for hop in range(1, hops + 1):
            if not frontier:
                break
            nb = self._neighbours(res, sorted(frontier))
            nxt = set()
            for v in frontier:
                nxt |= nb.get(v, set()) - res.hop_of.keys()
            for v in nxt:
                res.hop_of[v] = hop
            frontier = nxt - self.hubs
        res.timings_ms["expand"] = (time.perf_counter() - t0) * 1e3

        t0 = time.perf_counter()
        ents = [v for v in res.hop_of if v not in self.hubs]
        rows = [{"id": v} for v in ents]
        for i in range(0, len(rows), 1000):
            for e, c in self._q(res, CHUNKS_BATCH, {"rows": rows[i:i + 1000]}):
                doc = self.chunk_of[c].split("_chunk_")[0]
                res.doc_scores[doc] = res.doc_scores.get(doc, 0.0) + 1 / 2 ** res.hop_of[e]
                res.doc_min_hop[doc] = min(res.doc_min_hop.get(doc, 9), res.hop_of[e])
        res.timings_ms["chunks"] = (time.perf_counter() - t0) * 1e3
        return res

    def candidate_docs(self, res: GraphResult, hops: int) -> list[str]:
        """Pool handed to the reranker: every 1-hop doc, or the top HOP2_CAP at 2 hops."""
        return res.pool(1) if hops <= 1 else res.pool(hops, HOP2_CAP)
