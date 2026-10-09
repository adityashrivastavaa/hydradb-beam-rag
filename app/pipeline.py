"""Graph first pass + reranker second pass -> top-k documents."""
from __future__ import annotations

import time

from .config import DEFAULT_HOPS, TOP_K
from .documents import load_documents
from .graph import GraphRetriever
from .rerank import Reranker


class Pipeline:
    def __init__(self):
        self.docs = load_documents()
        self.graph = GraphRetriever()
        self.reranker = Reranker()

    def retrieve(self, question: str, k: int = TOP_K, hops: int = DEFAULT_HOPS) -> dict:
        t0 = time.perf_counter()
        g = self.graph.retrieve(question, hops)
        pool = [d for d in self.graph.candidate_docs(g, hops) if d in self.docs]
        t1 = time.perf_counter()
        scores = self.reranker.score(question, [self.docs[d] for d in pool])
        t2 = time.perf_counter()
        ranked = sorted(zip(pool, scores), key=lambda x: -x[1])[:k]
        return {
            "question": question,
            "hops": hops,
            "seeds": sorted(set(g.seeds.values())),
            "candidates_tried": g.candidates,
            "pool_size": len(pool),
            "chunks": [{"rank": i, "doc_id": d, "rerank_score": round(s, 4),
                        "graph_score": round(g.doc_scores[d], 3), "graph_hop": g.doc_min_hop[d],
                        "text": self.docs[d]} for i, (d, s) in enumerate(ranked, 1)],
            "timings_ms": {**{k_: round(v, 1) for k_, v in g.timings_ms.items()},
                           "graph_total": round((t1 - t0) * 1e3, 1),
                           "rerank": round((t2 - t1) * 1e3, 1),
                           "total": round((t2 - t0) * 1e3, 1)},
            "graph_requests": g.requests,
            "graph": self.graph.subgraph(g),
            "reranker": self.reranker.model_name,
        }
