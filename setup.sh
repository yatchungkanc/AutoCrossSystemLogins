#!/usr/bin/env bash
# Bootstrap script for projectHotGates.
# Run once after cloning:  ./setup.sh
set -euo pipefail

AGENT_DIR="$(cd "$(dirname "$0")/dashboard-agent" && pwd)"
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/.venv"
ENV_FILE="$AGENT_DIR/.env"
ENV_EXAMPLE="$AGENT_DIR/.env.example"

echo "=== projectHotGates setup ==="
echo ""

# ── 1. Python check ──────────────────────────────────────────────────────────
PYTHON=$(command -v python3 || command -v python || true)
if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.11+ not found. Install it and re-run this script."
    exit 1
fi

PY_VER=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11) ]]; then
    echo "ERROR: Python 3.11+ required (found $PY_VER). Please upgrade and re-run."
    exit 1
fi

echo "[1/4] Python $PY_VER found."

# ── 2. Virtual environment ────────────────────────────────────────────────────
if [[ -d "$VENV_DIR" ]]; then
    echo "[2/4] Virtual environment already exists at .venv — skipping creation."
else
    echo "[2/4] Creating virtual environment at .venv..."
    "$PYTHON" -m venv "$VENV_DIR"
fi

# Activate venv for the remainder of this script
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "      Installing dependencies from dashboard-agent/pyproject.toml..."
pip install --quiet -e "$AGENT_DIR"

# ── 3. Playwright / Chromium ──────────────────────────────────────────────────
echo "[3/4] Installing Playwright Chromium browser..."
playwright install chromium

# ── 4. .env file ─────────────────────────────────────────────────────────────
if [[ -f "$ENV_FILE" ]]; then
    echo "[4/4] dashboard-agent/.env already exists — skipping."
else
    cp "$ENV_EXAMPLE" "$ENV_FILE"
    echo "[4/4] Created dashboard-agent/.env from .env.example."
    echo "      → Open dashboard-agent/.env and fill in your credentials before running."
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Activate your environment:  source .venv/bin/activate"
echo ""
echo "Then run:"
echo "  python run.py               # open all dashboards"
echo "  python run.py cloudhealth   # generate CloudHealth report"
echo ""
echo "First run will open a browser for manual SSO setup."
