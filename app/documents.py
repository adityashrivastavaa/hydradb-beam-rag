"""Document text for the conversation: one ingested source = one BEAM turn.

The graph links entities to chunk ids `<doc>_chunk_NNNN`; text is held per
document (as served by HydraDB's /context/inspect), so retrieval and reranking
work at document granularity. A typical document is ~5k characters.
"""
from __future__ import annotations

import json
import re

from .config import DATA_DIR

# BEAM appends message-index markers ("->-> 9,12") to user messages; they are
# evaluation bookkeeping, not conversation content.
_MARKER = re.compile(r"\s*->->\s*[\d,\s]*")


def _render(raw: str) -> str:
    try:
        pairs = json.loads(raw).get("pairs", [])
    except (ValueError, AttributeError):
        return _MARKER.sub(" ", raw)
    return "\n".join(f"User: {_MARKER.sub(' ', p.get('user', '')).strip()}\n"
                     f"Assistant: {p.get('assistant', '').strip()}" for p in pairs)


def load_documents() -> dict[str, str]:
    raw = json.loads((DATA_DIR / "documents.json").read_text())
    return {doc_id: _render(text) for doc_id, text in raw.items()}
