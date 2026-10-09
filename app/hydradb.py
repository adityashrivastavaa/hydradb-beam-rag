"""Minimal client for a local HydraDB graph-node's HTTP query API."""
from __future__ import annotations

import http.client
import json
import os
import threading
import time

_local = threading.local()


class QueryError(Exception):
    pass


class HydraDB:
    def __init__(self, host: str | None = None, port: int | None = None, token: str | None = None,
                 graph: str = "default", cell: str = "cell-0", namespace: str = "default"):
        self.host = host or os.getenv("HYDRADB_HOST", "127.0.0.1")
        self.port = port or int(os.getenv("HYDRADB_HTTP_PORT", "8443"))
        token = token or os.getenv("HYDRADB_TOKEN", "local-development-token-32-bytes")
        self.graph, self.cell = graph, cell
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                        "X-Graph-Namespace": namespace}

    def _conn(self) -> http.client.HTTPConnection:
        # One keep-alive connection per thread.
        c = getattr(_local, "conn", None)
        if c is None:
            c = _local.conn = http.client.HTTPConnection(self.host, self.port, timeout=120)
        return c

    def query(self, cypher: str, params: dict | None = None, page_size: int = 4096) -> list[list]:
        """Run one query and follow cursors. page_size is resent on every page because
        the server does not remember it between pages."""
        body = {"cell_id": self.cell, "query": cypher, "parameters": params or {}, "page_size": page_size}
        rows: list[list] = []
        while True:
            out = self._post(body)
            rows.extend([_cell(v) for v in r] for r in out.get("rows", []))
            cur = out.get("next_cursor")
            if not cur:
                return rows
            body = {**body, "cursor": cur, "query_id": out.get("query_id")}

    def timed(self, cypher: str, params: dict | None = None) -> tuple[list[list], float]:
        t0 = time.perf_counter()
        rows = self.query(cypher, params)
        return rows, time.perf_counter() - t0

    def _post(self, body: dict) -> dict:
        data = json.dumps(body)
        for attempt in range(2):
            c = self._conn()
            try:
                c.request("POST", f"/v1/graphs/{self.graph}/query", data, self.headers)
                resp = c.getresponse()
                raw = resp.read()
                break
            except (http.client.HTTPException, ConnectionError):
                c.close()
                _local.conn = None
                if attempt:
                    raise
        out = json.loads(raw) if raw else {}
        if resp.status != 200:
            raise QueryError(f"HTTP {resp.status}: {out.get('error', out)}")
        return out


def _cell(v):
    if isinstance(v, dict) and "type" in v:
        if v["type"] == "list":
            return [_cell(x) for x in v.get("value") or []]
        return v.get("value")
    return v
