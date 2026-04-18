#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"

if [ ! -d "$VENV_DIR" ]; then
  echo "ERROR: Virtual environment not found at $VENV_DIR" >&2
  echo "Run ./setup_env.sh first." >&2
  return 1 2>/dev/null || exit 1
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "Activated virtual environment: $VIRTUAL_ENV"
