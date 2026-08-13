#!/usr/bin/env bash
set -euo pipefail
if [[ ! -x .venv/bin/python ]]; then echo ".venv not found" >&2; exit 1; fi
echo "Starting ContextBridge local dashboard on http://127.0.0.1:8765"
exec .venv/bin/python -m contextbridge.dashboard
