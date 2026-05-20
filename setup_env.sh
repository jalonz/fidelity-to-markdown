#!/usr/bin/env bash
set -euo pipefail

VENV_DIR=".venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "ERROR: Python interpreter '$PYTHON_BIN' not found." >&2
  exit 1
fi

# On Debian/Ubuntu-based systems (Ubuntu, Zorin OS, etc.), ensure python3-venv
# is installed — it bundles ensurepip, which gives the venv its own pip.
# Skipped silently on other distros.
if command -v apt-get >/dev/null 2>&1 && ! dpkg -s python3-venv >/dev/null 2>&1; then
  echo "The OS package 'python3-venv' is required to create the virtual environment."
  read -r -p "Install it now via 'sudo apt-get install'? [Y/n] " reply
  case "${reply,,}" in
    ""|y|yes)
      sudo apt-get update
      sudo apt-get install -y python3-venv
      ;;
    *)
      echo "Skipping package install. 'python3 -m venv' may fail without it." >&2
      ;;
  esac
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
