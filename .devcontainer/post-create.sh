#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "[devcontainer] Installing backend dependencies with uv..."
cd "${REPO_ROOT}/backend"
uv sync --all-packages --all-groups --frozen

echo "[devcontainer] Installing frontend dependencies..."
cd "${REPO_ROOT}/frontend"
corepack enable
if [[ -f "yarn.lock" ]]; then
    corepack prepare yarn@1 --activate
    yarn install --frozen-lockfile
elif [[ -f "package-lock.json" ]]; then
    npm ci
else
    npm install
fi

echo "[devcontainer] Setup complete."
