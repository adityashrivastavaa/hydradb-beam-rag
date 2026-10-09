"""Second pass: a local cross-encoder scores (question, document) pairs."""
from __future__ import annotations

import numpy as np
import torch
from sentence_transformers import CrossEncoder

from .config import RERANKER_MAX_LENGTH, RERANKER_MODEL


def _device() -> str:
    if torch.backends.mps.is_available():
        return "mps"
    return "cuda" if torch.cuda.is_available() else "cpu"


class Reranker:
    def __init__(self, model: str = RERANKER_MODEL, max_length: int = RERANKER_MAX_LENGTH):
        self.model_name = model
        self.device = _device()
        self.model = CrossEncoder(model, device=self.device, max_length=max_length, trust_remote_code=True)

    def score(self, question: str, texts: list[str], batch_size: int = 16) -> list[float]:
        if not texts:
            return []
        s = self.model.predict([(question, t) for t in texts], batch_size=batch_size, show_progress_bar=False)
        return np.asarray(s, dtype=float).ravel().tolist()
