#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter '$PYTHON_BIN' not found." >&2
  exit 1
fi

if [ ! -d "$VENV_DIR" ]; then
  "$PYTHON_BIN" -m venv "$VENV_DIR"
  echo "Created virtual environment at $VENV_DIR"
else
  echo "Using existing virtual environment at $VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo
echo "Environment ready. Activate it with:"
echo "  source activate_env.sh"
