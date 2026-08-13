# ContextBridge — Integrated MCP Chat (v0.9.1)

**Secure MCP gateway for authenticated developer infrastructure.**

ContextBridge lets an MCP-capable AI read authenticated GitHub data through semantic tools, records
every tool execution in SQLite, routes mutations into a signed human-confirmation queue, and includes the Milestone 7 **100-case evaluation framework** plus the new Milestone 9 **local React control-plane dashboard**.

Milestone **6B is intentionally skipped** in this build. The project remains:

```dotenv
CONTEXTBRIDGE_DRY_RUN=true
GITHUB_WRITES_ENABLED=false
```

So an approved mutation is still simulated and **no GitHub write request is sent**.

## Upgrade your existing installation

This ZIP is designed to be extracted directly over the ContextBridge folder you already have from
Milestone 7. It intentionally excludes `.env`, `.venv`, runtime SQLite files, your GitHub token,
and the local action-signing key.

On Windows, extract/overwrite the files and run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade_windows.ps1
```

The upgrade script preserves your existing state, installs only new Python dependencies, migrates
the database in place, runs the full test suite, reruns the mutation/confirmation safety checks,
executes the 100-case evaluation smoke test, and verifies the React dashboard without opening a
network listener.

## Current architecture

```text
AI / MCP host
     |
     v
+-------------------------------+
| ContextBridge MCPServer       |
| 27 semantic tools             |
+---------------+---------------+
                |
      +---------+----------+
      |                    |
      v                    v
GitHub read layer       Mutation request
      |                    |
      v                    v
GitHub REST          signed pending_action
                           |
                  X  no MCP approval tool
                           |
             +-------------+-------------+
             |                           |
             v                           v
      Local CLI human              React dashboard human
             |                           |
             +-------------+-------------+
                           |
                           v
                  approved one-time action
                           |
                           v
                  DRY_RUN simulation only

Every tool call ----------> SQLite telemetry/audit
100-case evaluations -----> SQLite eval history
SQLite -------------------> React control plane
```

## MCP tool surface

### System / GitHub connection

- `server_info`
- `health`
- `github_connection_status`

### GitHub read-only

- `list_repositories`
- `get_repository`
- `search_issues`
- `get_issue`
- `list_pull_requests`
- `get_pull_request`
- `list_commits`
- `get_file_contents`
- `search_code`
- `get_workflow_runs`
- `get_commit_status`

### Observability / evaluation

- `get_tool_metrics`
- `get_recent_tool_calls`
- `get_audit_summary`
- `get_evaluation_summary`

### Policy / human confirmation

- `get_write_policy`
- `list_pending_actions`
- `get_pending_action`
- `execute_approved_action`

### Mutation requests — confirmation required, still dry-run

- `create_issue`
- `add_issue_comment`
- `add_labels`
- `close_issue`
- `reopen_issue`

**Total: 27 MCP tools.**

There is deliberately no MCP tool for approval/rejection, repository deletion, file mutation,
commit pushing, branch deletion, force-push, PR merge, repository settings mutation, or workflow
mutation.

---

# Milestone 7 — Evaluation framework

The bundled benchmark contains **100 prompts** spanning GitHub reads, issue mutations, operational
telemetry, confirmation flow, and evaluation introspection.

Metrics include:

- tool-selection accuracy;
- partial parameter accuracy;
- read/write/destructive risk classification accuracy;
- mutation/confirmation classification accuracy;
- per-tool accuracy;
- top tool confusions;
- case-level results persisted in SQLite.

Run the deterministic offline baseline:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py --baseline
```

The baseline is deliberately a **keyword router used to verify the scoring pipeline**. Its score is
not an LLM benchmark claim.

To score an actual AI/MCP host, export predictions like:

```json
[
  {
    "id": "get_repository-01",
    "actual_tool": "get_repository",
    "actual_arguments": {
      "owner": "Vatsal212005",
      "repo": "FeatureForge"
    }
  }
]
```

Then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py --predictions evals\my_predictions.json
```

Evaluation runs are stored in:

```text
evaluation_runs
evaluation_results
```

and immediately appear in the dashboard.

See [`evals/README.md`](evals/README.md) and [`docs/EVALUATION.md`](docs/EVALUATION.md).
A concise interview/demo flow is in [`docs/DEMO.md`](docs/DEMO.md).

---

# Milestone 9 — Local React control plane

Start it with:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

Then open:

```text
http://127.0.0.1:8765
```

The shipping dashboard is prebuilt and self-contained, so **Node/npm is not required to run it**.
The React source is included under `frontend/` for portfolio/review purposes.

The dashboard contains:

- Overview — call volume, success rate, latency, pending actions, latest evaluation score;
- Approvals — exact signed pending actions with human approve/reject controls;
- Audit — redacted execution/audit history;
- Evaluations — benchmark history, accuracy metrics, confusions, offline baseline trigger;
- Tools — all semantic tools and risk classes;
- Security — current dry-run/write/approval posture.

### Dashboard safety

The dashboard defaults to:

```dotenv
CONTEXTBRIDGE_DASHBOARD_HOST=127.0.0.1
CONTEXTBRIDGE_DASHBOARD_PORT=8765
CONTEXTBRIDGE_DASHBOARD_TOKEN=
```

If you try to bind it to a non-loopback address, ContextBridge refuses to start unless
`CONTEXTBRIDGE_DASHBOARD_TOKEN` is configured.

Dashboard approval is still **out-of-band from MCP**. The browser sends the decision to the local
control-plane API using actor `human:local_dashboard`; the AI has no MCP capability that can call
that approval endpoint.

For each approval/rejection, the UI requires the human to type `APPROVE` or `REJECT` exactly.

---

## SQLite schema

Existing data is migrated in place to schema **v3**.

```text
schema_meta
tool_executions
audit_events
pending_actions
system_events
evaluation_runs
evaluation_results
```

Your Windows installation continues using the database path already established by Milestone 4,
normally:

```text
C:\Users\<you>\AppData\Local\ContextBridge\contextbridge.db
```

The action signing key remains beside the database and is not packaged into source control.

## Safety posture while 6B is skipped

```text
Repository deletion       NOT IMPLEMENTED
File/code modification    NOT IMPLEMENTED
Commit pushing            NOT IMPLEMENTED
Branch deletion           NOT IMPLEMENTED
Force push                NOT IMPLEMENTED
PR merge                   NOT IMPLEMENTED
Repo settings changes     NOT IMPLEMENTED
Workflow mutation          NOT IMPLEMENTED

Issue mutation request    -> signed human confirmation
Human approval            -> out-of-band CLI/dashboard
Approved execution        -> DRY-RUN simulation
Actual GitHub mutation    -> DISABLED
```

Do not change your GitHub PAT to write access for Milestone 9. Your existing read-only token is
sufficient because 6B remains skipped.

## Useful commands

```powershell
# full tests
.\.venv\Scripts\python.exe -m pytest

# MCP smoke test
.\.venv\Scripts\python.exe scripts\smoke_test.py

# real GitHub read check
.\.venv\Scripts\python.exe scripts\github_read_check.py

# telemetry
.\.venv\Scripts\python.exe scripts\telemetry_check.py

# pending human actions
.\.venv\Scripts\python.exe scripts\action_cli.py list --status pending

# offline evaluation baseline
.\.venv\Scripts\python.exe scripts\run_evals.py --baseline

# dashboard
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

## Repository layout

```text
contextbridge/
├── evals/                        # 100-case benchmark + prediction format
├── frontend/                     # React source
├── docs/
├── scripts/
├── src/contextbridge/
│   ├── dashboard.py              # local FastAPI control plane
│   ├── dashboard_static/         # prebuilt React runtime
│   ├── eval_data/                # packaged benchmark
│   ├── evaluation.py             # scoring/persistence
│   ├── github/
│   ├── security/
│   ├── telemetry/
│   └── tools/
├── tests/
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── pyproject.toml
```

## Status

```text
M1   MCP foundation                         complete
M2   GitHub client/auth infrastructure       complete
M3   GitHub read tools                       complete
M4   SQLite telemetry/audit                  complete
M5   permission engine + dry-run mutations   complete
M6A  signed human confirmation               complete
M6B  live GitHub writes                      intentionally skipped
M7   evaluation framework                    complete
M8   React control plane + polish            complete
```

The project is therefore feature-complete for the **safe/dry-run portfolio build**, while keeping
live mutation activation as an explicit future decision rather than silently widening GitHub
permissions.


# Milestone 9 — Integrated MCP Chat

The local React control plane now includes a **Chat** page. The browser sends the user message only
to the local FastAPI dashboard backend. Model and GitHub credentials remain server-side. The backend
opens a real in-process MCP `Client` against the ContextBridge `MCPServer`, exposes the discovered tool
schemas to the configured model, executes tool calls through MCP, and persists chat messages plus the
tool timeline in SQLite.

## Configure a model provider

### Gemini (default)

ContextBridge v0.9.1 uses Gemini by default:

```dotenv
CONTEXTBRIDGE_LLM_PROVIDER=gemini
CONTEXTBRIDGE_LLM_MODEL=gemini-3.6-flash
GEMINI_API_KEY=
```

Gemini function calls are executed manually by ContextBridge through its own MCP client. The model can select a tool and arguments, but the Google SDK never bypasses ContextBridge's read-only filtering, telemetry, risk policy, signed pending actions, or human-confirmation controls.

### OpenAI

OpenAI remains supported:

```dotenv
CONTEXTBRIDGE_LLM_PROVIDER=openai
CONTEXTBRIDGE_LLM_MODEL=gpt-5-mini
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com
```

OpenAI requests use the Responses API with `store=false`. Tool results required for the current turn are transmitted to the configured model provider.

Repository content sent to a hosted model is transmitted to that provider; use Ollama when you require a fully local model path.

### Ollama / local model

Install and run Ollama separately, pull a tool-capable model, then configure:

```dotenv
CONTEXTBRIDGE_LLM_PROVIDER=ollama
CONTEXTBRIDGE_LLM_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

The exact local model is intentionally configurable because tool-calling quality differs significantly
between models.

## Chat safety

- Chat defaults to **read-only mode**.
- In read-only mode, mutation tools are not exposed to the model.
- Turning the Chat read-only toggle off only exposes the existing mutation-request tools; the existing
  signed pending-action and out-of-band human-confirmation pipeline still applies.
- Milestone 6B remains disabled by this upgrade: `CONTEXTBRIDGE_DRY_RUN=true` and
  `GITHUB_WRITES_ENABLED=false` are preserved and checked by the upgrade script.
- Model credentials, GitHub credentials, and the action-signing key are never returned by dashboard APIs.
- Tool output is treated as untrusted data by the chat system instructions to reduce prompt-injection risk.
- Chat sessions, messages, and model/tool timelines are stored only in the existing local SQLite DB.

## Chat persistence tables

Schema v4 adds:

```text
chat_sessions
chat_messages
chat_tool_calls
```

This lets the dashboard keep conversation history and lets each assistant answer be correlated with the
MCP operations used to produce it.
