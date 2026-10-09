#!/usr/bin/env bash
# Create .venv, install dependencies, and pre-download the spaCy model and reranker.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m spacy download en_core_web_sm
.venv/bin/python - <<'EOF'
from app.config import RERANKER_MODEL
from huggingface_hub import snapshot_download
print("downloading", RERANKER_MODEL)
snapshot_download(RERANKER_MODEL)
EOF
echo "python env ready: source .venv/bin/activate"
