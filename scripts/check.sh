#!/usr/bin/env bash
# Unified local gate (Linux/macOS/CI-style). Usage: bash scripts/check.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo
echo "== Python =="
cd "$ROOT/python"
python3.11 -m pip install -q -r requirements.txt
python3.11 -m pip install -q -e ".[dev]"
python3.11 -m pytest -q --timeout=60 -m "not live"
python3.11 -m slash.export_manifest --check

echo
echo "== GUI =="
cd "$ROOT/gui"
if [[ ! -d node_modules ]]; then npm ci; fi
npm run typecheck
npm test

echo
echo "== cli-ts =="
cd "$ROOT/cli-ts"
if [[ ! -d node_modules ]]; then npm ci; fi
npm run typecheck

echo
echo "All checks passed."
