"""Shared settings. Everything is overridable through environment variables."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("BEAM_DATA_DIR", ROOT / "data" / "beam_c01"))

# Labels stored on every node (queries filter on SUB_TENANT only).
TENANT = "beam1m"
SUB_TENANT = "memories_c_01"

# Retrieval defaults (see README "How the defaults were chosen").
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")
RERANKER_MAX_LENGTH = int(os.getenv("RERANKER_MAX_LENGTH", "512"))
DEFAULT_HOPS = int(os.getenv("GRAPH_HOPS", "2"))
HOP2_CAP = int(os.getenv("HOP2_CAP", "150"))  # documents reranked at 2 hops
HUB_DEGREE = 500  # same super-node threshold as production; hubs are never expanded
TOP_K = 30

# Answering.
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")
