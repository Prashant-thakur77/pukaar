#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is required" >&2
  exit 1
fi

cd "$BACKEND_DIR"
if [[ ! -d .venv ]]; then
  uv venv
fi
source .venv/bin/activate
uv pip install -e .[dev]

cd "$BACKEND_DIR"
PYTHONPATH=src python -m Pukaar.scripts.seed

cd "$FRONTEND_DIR"
npm install --legacy-peer-deps

echo "Setup complete."
