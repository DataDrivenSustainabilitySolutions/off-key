#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[devcontainer] Installing backend dependencies with uv..."
cd "${REPO_ROOT}/backend"
uv sync --all-packages --all-groups --frozen

echo "[devcontainer] Installing frontend dependencies..."
cd "${REPO_ROOT}/frontend"
if [[ -f "package-lock.json" ]]; then
    npm ci
else
    npm install
fi

echo "[devcontainer] Setup complete."
