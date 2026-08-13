#!/usr/bin/env bash
set -euo pipefail

echo "ContextBridge v0.9.1 - native Gemini integrated-chat upgrade (6B still skipped)"

if [[ ! -x .venv/bin/python ]]; then
  echo ".venv was not found. Run scripts/setup_unix.sh once first." >&2
  exit 1
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example"
else
  echo "Keeping existing .env and local runtime state"
fi

python3 - <<'PY'
from pathlib import Path
import re
p=Path('.env')
text=p.read_text(encoding='utf-8')
def get(name):
    m=re.search(rf'(?m)^\s*{re.escape(name)}\s*=\s*(.*)\s*$', text)
    return m.group(1).strip() if m else None

def setv(name,value):
    global text
    pat=rf'(?m)^\s*{re.escape(name)}\s*=.*$'
    line=f'{name}={value}'
    if re.search(pat,text): text=re.sub(pat,line,text)
    else:
        if text and not text.endswith('\n'): text+='\n'
        text+=line+'\n'

if get('CONTEXTBRIDGE_DRY_RUN') is None: setv('CONTEXTBRIDGE_DRY_RUN','true')
if get('GITHUB_WRITES_ENABLED') is None: setv('GITHUB_WRITES_ENABLED','false')
if (get('CONTEXTBRIDGE_DRY_RUN') or '').lower() != 'true': raise SystemExit('Safety preflight failed: CONTEXTBRIDGE_DRY_RUN must remain true.')
if (get('GITHUB_WRITES_ENABLED') or '').lower() != 'false': raise SystemExit('Safety preflight failed: GITHUB_WRITES_ENABLED must remain false.')
setv('CONTEXTBRIDGE_LLM_PROVIDER','gemini')
setv('CONTEXTBRIDGE_LLM_MODEL','gemini-3.6-flash')
if get('GEMINI_API_KEY') is None: setv('GEMINI_API_KEY','')
p.write_text(text,encoding='utf-8')
PY

.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python scripts/smoke_test.py
.venv/bin/python scripts/gemini_check.py
.venv/bin/python scripts/chat_check.py
.venv/bin/python scripts/dashboard_check.py

echo "Upgrade complete. Add GEMINI_API_KEY to .env, restart the dashboard, and open Chat."
