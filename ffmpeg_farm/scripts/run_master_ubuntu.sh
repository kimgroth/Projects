#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

"$SCRIPT_DIR/install_ubuntu.sh"

source "$PROJECT_DIR/.venv/bin/activate"
cd "$PROJECT_DIR"
exec python -m ffarm master --host 0.0.0.0 --port 8000
