#!/usr/bin/env bash
# Build HydraDB graph-node (release) from source.
#
#   HYDRADB_DIR=~/src/hydradb scripts/install_hydradb.sh
#
# Uses an existing checkout at $HYDRADB_DIR, or clones the repo there.
# Native dependencies (macOS, Homebrew):
#   brew install just cmake pkg-config llvm suite-sparse
#   brew install cleishm/neo4j/libcypher-parser     # needs the tap; the bare name fails
# Ubuntu/WSL:
#   sudo apt-get install -y build-essential clang libclang-dev cmake pkg-config \
#     libcypher-parser-dev libgraphblas-dev
# Rust: install with rustup (https://rustup.rs); the repo pins its toolchain.
set -euo pipefail

HYDRADB_DIR="${HYDRADB_DIR:-$HOME/src/hydradb}"
# Open-source HydraDB repo; override HYDRADB_REPO to build from a fork.
HYDRADB_REPO="${HYDRADB_REPO:-https://github.com/hydra-db/hydradb.git}"

if [ ! -d "$HYDRADB_DIR/.git" ]; then
  git clone "$HYDRADB_REPO" "$HYDRADB_DIR"
fi

# Homebrew's rustup does not put `cargo` on PATH; fall back to the pinned toolchain directly.
if ! command -v cargo >/dev/null 2>&1; then
  channel="$(sed -n 's/^channel *= *"\(.*\)"/\1/p' "$HYDRADB_DIR/rust-toolchain.toml")"
  rustup toolchain install "$channel" >/dev/null
  PATH="$(dirname "$(rustup which --toolchain "$channel" cargo)"):$PATH"
  export PATH
fi

# The FFI crates need these on macOS; graph-node's query futures need the bigger stack everywhere.
if command -v brew >/dev/null 2>&1; then
  export BINDGEN_EXTRA_CLANG_ARGS="-I$(brew --prefix)/include"
  export LIBRARY_PATH="$(brew --prefix)/lib"
fi
export RUST_MIN_STACK=33554432

cd "$HYDRADB_DIR"
cargo build --locked --release --features server-runtime --bin graph-node
echo "built: $HYDRADB_DIR/target/release/graph-node"
