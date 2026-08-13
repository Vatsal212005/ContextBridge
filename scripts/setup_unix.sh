#!/usr/bin/env bash
set -euo pipefail
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
[[ -f .env ]] || cp .env.example .env
python -m pytest
python scripts/smoke_test.py
python scripts/evaluation_check.py
python scripts/dashboard_check.py
echo "Setup complete."
echo "MCP: .venv/bin/contextbridge"
echo "Dashboard: ./scripts/start_dashboard.sh"
