#!/usr/bin/env bash
# Run a single-node HydraDB backed by a local directory (foreground; Ctrl-C to stop).
#
#   HYDRADB_DIR=~/src/hydradb scripts/start_hydradb.sh
#
# Ports: HTTP query API 8443, Bolt 7687, admin (readyz/metrics) 19090. The admin
# port defaults to 19090 because Docker Desktop often holds 9090/9091.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HYDRADB_DIR="${HYDRADB_DIR:-$HOME/src/hydradb}"
BIN="${GRAPH_NODE_BIN:-$HYDRADB_DIR/target/release/graph-node}"
STATE="${HYDRADB_STATE_DIR:-$ROOT/.hydradb}"
HTTP_PORT="${HYDRADB_HTTP_PORT:-8443}"
BOLT_PORT="${HYDRADB_BOLT_PORT:-7687}"
ADMIN_PORT="${HYDRADB_ADMIN_PORT:-19090}"

[ -x "$BIN" ] || { echo "graph-node not found at $BIN - run scripts/install_hydradb.sh" >&2; exit 1; }
mkdir -p "$STATE/store" "$STATE/cache"
[ -f "$STATE/auth-token" ] || printf '%s\n' "${HYDRADB_TOKEN:-local-development-token-32-bytes}" > "$STATE/auth-token"

export CLOUD_PROVIDER=local
export LOCAL_PATH="$STATE/store"
export GRAPH_NAMESPACE=default GRAPH_ID=default GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_NODE_ID=node-0
export GRAPH_HTTP_ADDR="127.0.0.1:$HTTP_PORT"
export GRAPH_BOLT_ADDR="127.0.0.1:$BOLT_PORT"
export GRAPH_ADMIN_ADDR="127.0.0.1:$ADMIN_PORT"
export GRAPH_BOLT_NODE_ADDRESSES="node-0=127.0.0.1:$BOLT_PORT"
export GRAPH_ADVERTISED_BOLT_ADDR="127.0.0.1:$BOLT_PORT"
export GRAPH_DATA_CACHE_DIR="$STATE/cache"
export GRAPH_DATA_CACHE_PART_BYTES=4194304
export GRAPH_DATA_CACHE_MAX_OPEN_FILES=512
export GRAPH_AUTH_TOKEN_FILE="$STATE/auth-token"
export GRAPH_ALLOW_PLAINTEXT=true
export RUST_MIN_STACK=33554432   # without it the node aborts on the first query

echo "HydraDB: http://127.0.0.1:$HTTP_PORT  bolt://127.0.0.1:$BOLT_PORT  admin http://127.0.0.1:$ADMIN_PORT/readyz"
exec "$BIN"
