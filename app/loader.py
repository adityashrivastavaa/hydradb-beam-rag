"""Load the bundled BEAM-1M conversation graph into a running HydraDB node.

  python -m app.loader            # loads data/beam_c01/graph.json

Schema (matches what the HydraDB application queries):

  (:Entity {id, entity_id, name, type, tenant_id, sub_tenant_id})
  (:Chunk  {id, chunk_id, timestamp, tenant_id, sub_tenant_id})
  (:Entity)-[:RELATES {chunk_id, timestamp, raw_relation, canonical_relation,
                       metadata, relationship_id, weight}]->(:Entity)
  (:Entity)-[:PRESENT_IN]->(:Chunk)

HydraDB vertex ids are integers assigned here (entities 1..N, chunks N+1..N+M);
the mapping is written to data/beam_c01/idmap.json for the query side.

Nodes are written first (labelled), then edges, so no node is ever unlabelled.
RELATES carries properties, which the UNWIND edge batch cannot write, so
those go one statement per edge, concurrently (~2 minutes for c_01).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from .config import DATA_DIR, SUB_TENANT, TENANT
from .hydradb import HydraDB

BATCH = 1000  # server cap is 1024 items per UNWIND

NODE_ENTITY = ("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Entity, "
               "n.entity_id = row.entity_id, n.name = row.name, n.type = row.type, "
               "n.tenant_id = row.tenant_id, n.sub_tenant_id = row.sub_tenant_id")
NODE_CHUNK = ("UNWIND $rows AS row MERGE (n {id: row.id}) SET n:Chunk, "
              "n.chunk_id = row.chunk_id, n.timestamp = row.timestamp, "
              "n.tenant_id = row.tenant_id, n.sub_tenant_id = row.sub_tenant_id")
EDGE_PRESENT_IN = "UNWIND $rows AS row CREATE (a {id: row.src})-[:PRESENT_IN]->(b {id: row.dst})"
EDGE_RELATES = ("CREATE (a {id: $s})-[:RELATES {chunk_id: $chunk_id, timestamp: $ts, "
                "raw_relation: $pred, canonical_relation: $pred, metadata: $metadata, "
                "relationship_id: $rid, weight: 1.0}]->(b {id: $t})")
COUNT_RELATES = "MATCH (a:Entity {sub_tenant_id: $st})-[:RELATES]->(b:Entity) RETURN count(*) AS n"


def build(g: dict):
    ents = sorted(g["entities"], key=lambda e: e["id"])
    eid = {e["id"]: i + 1 for i, e in enumerate(ents)}
    chunk_ts: dict[str, int] = {}
    for e in g["edges"]:
        chunk_ts[e["chunk_id"]] = max(int(e["ts"]), chunk_ts.get(e["chunk_id"], 0))
    chunk_ids = sorted({c for _, c in g["present_in"]} | set(chunk_ts))
    cid = {c: len(eid) + i + 1 for i, c in enumerate(chunk_ids)}
    common = {"tenant_id": TENANT, "sub_tenant_id": SUB_TENANT}
    entity_rows = [{"id": eid[e["id"]], "entity_id": e["id"], "name": e["name"], "type": e["type"], **common}
                   for e in ents]
    chunk_rows = [{"id": cid[c], "chunk_id": c, "timestamp": chunk_ts.get(c, 0), **common} for c in chunk_ids]
    present_rows = [{"src": eid[e], "dst": cid[c]} for e, c in g["present_in"]]
    relates = [{"s": eid[e["s"]], "t": eid[e["t"]], "chunk_id": e["chunk_id"], "ts": int(e["ts"]),
                "pred": e["pred"] or "", "metadata": json.dumps({"context": e["context"]}),
                "rid": f"rel_{i:06d}"} for i, e in enumerate(g["edges"])]
    return eid, cid, entity_rows, chunk_rows, present_rows, relates


def batched(tl: HydraDB, cypher: str, rows: list, label: str):
    t0 = time.perf_counter()
    for i in range(0, len(rows), BATCH):
        tl.query(cypher, {"rows": rows[i:i + BATCH]})
    print(f"  {label}: {len(rows)} in {time.perf_counter() - t0:.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--force", action="store_true", help="load even if the graph already has RELATES edges")
    a = ap.parse_args()

    tl = HydraDB()
    g = json.loads((DATA_DIR / "graph.json").read_text())
    existing = tl.query(COUNT_RELATES, {"st": SUB_TENANT})[0][0]
    if existing and not a.force:
        raise SystemExit(f"graph already loaded ({existing} RELATES edges). Use a fresh store, or --force.")

    eid, cid, entity_rows, chunk_rows, present_rows, relates = build(g)
    (DATA_DIR / "idmap.json").write_text(json.dumps({"entities": eid, "chunks": cid}))
    print(f"loading {len(entity_rows)} entities, {len(chunk_rows)} chunks, "
          f"{len(relates)} RELATES, {len(present_rows)} PRESENT_IN", flush=True)
    batched(tl, NODE_ENTITY, entity_rows, "Entity nodes")
    batched(tl, NODE_CHUNK, chunk_rows, "Chunk nodes")
    batched(tl, EDGE_PRESENT_IN, present_rows, "PRESENT_IN edges")

    t0, errors = time.perf_counter(), []

    def one(row):
        try:
            tl.query(EDGE_RELATES, row)
        except Exception as e:
            errors.append((row["rid"], str(e)))

    with ThreadPoolExecutor(a.workers) as pool:
        for i, _ in enumerate(pool.map(one, relates), 1):
            if i % 1000 == 0:
                print(f"  RELATES edges: {i}/{len(relates)}", flush=True)
    print(f"  RELATES edges: {len(relates)} in {time.perf_counter() - t0:.1f}s, {len(errors)} errors", flush=True)
    for rid, msg in errors[:5]:
        print(f"    {rid}: {msg}")
    got = tl.query(COUNT_RELATES, {"st": SUB_TENANT})[0][0]
    print(f"verify: {got} RELATES edges in HydraDB (expected {len(relates)})")
    if got != len(relates):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
