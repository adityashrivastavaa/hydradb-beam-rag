"""Recall of the gold evidence documents in the returned top-k, over the BEAM c_01 questions.

  python -m eval.recall                 # default hops / reranker from app.config
  python -m eval.recall --hops 1 --k 30

Gold = the documents holding the evidence for each question (19 of the 20
questions have one; resolved from BEAM's source-message markers).
"""
from __future__ import annotations

import argparse
import json
import statistics

from app.config import DATA_DIR, DEFAULT_HOPS, TOP_K
from app.pipeline import Pipeline


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hops", type=int, default=DEFAULT_HOPS)
    ap.add_argument("--k", type=int, default=TOP_K)
    a = ap.parse_args()

    qs = [q for q in json.loads((DATA_DIR / "questions.json").read_text()) if q["gold_doc_ids"]]
    p = Pipeline()
    rows = []
    for q in qs:
        r = p.retrieve(q["question"], a.k, a.hops)
        got = [c["doc_id"] for c in r["chunks"]]
        gold = set(q["gold_doc_ids"])
        rec = {k: len(set(got[:k]) & gold) / len(gold) for k in (10, a.k)}
        rows.append((q, r, rec))
        print(f"{q['category'][:22]:22} R@10 {rec[10]:.2f}  R@{a.k} {rec[a.k]:.2f}  pool {r['pool_size']:4}  "
              f"{r['timings_ms']['total']:7.0f}ms  seeds={r['seeds'][:4]}", flush=True)
    print(f"\n{len(rows)} questions, hops={a.hops}, reranker={p.reranker.model_name}")
    for k in (10, a.k):
        print(f"  mean recall@{k}: {statistics.mean(x[2][k] for x in rows):.3f}")
    print(f"  hit@{a.k}: {statistics.mean(float(x[2][a.k] > 0) for x in rows):.3f}")
    print(f"  latency p50 {statistics.median(x[1]['timings_ms']['total'] for x in rows):.0f}ms "
          f"(graph {statistics.median(x[1]['timings_ms']['graph_total'] for x in rows):.0f}ms, "
          f"rerank {statistics.median(x[1]['timings_ms']['rerank'] for x in rows):.0f}ms)")


if __name__ == "__main__":
    main()
