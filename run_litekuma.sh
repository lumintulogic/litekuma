#!/usr/bin/env bash
# Entrypoint for LiteKuma Headless Uptime Monitor
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH}"

# Detect Python interpreter (prefer virtual environment if present)
if [ -z "$PYTHON_BIN" ]; then
    if [ -x "${SCRIPT_DIR}/.venv/bin/python" ]; then
        PYTHON_BIN="${SCRIPT_DIR}/.venv/bin/python"
    elif [ -x "${SCRIPT_DIR}/../.venv/bin/python" ]; then
        PYTHON_BIN="${SCRIPT_DIR}/../.venv/bin/python"
    elif command -v python3 >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    else
        PYTHON_BIN="python"
    fi
fi

exec "$PYTHON_BIN" -m litekuma "$@"
