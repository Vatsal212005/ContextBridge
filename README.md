# ContextBridge

**ContextBridge is a security-first Model Context Protocol (MCP) gateway that lets AI assistants inspect, reason over, and safely interact with GitHub repositories through a controlled, auditable tool layer.**

Instead of giving an LLM unrestricted access to GitHub credentials or letting it call arbitrary APIs directly, ContextBridge sits between the model and GitHub and exposes a deliberately scoped set of MCP tools. Every operation passes through explicit policy, telemetry, and safety controls.

The project combines:

- GitHub repository intelligence
- Model Context Protocol tooling
- Gemini, OpenAI, and local-model support
- MCP-native tool orchestration
- Human-in-the-loop mutation approvals
- Dry-run execution
- Repository allowlisting
- Signed approval records
- SQLite telemetry and audit logging
- Deterministic evaluation
- A local React control plane
- Persistent AI chat
- Tool-call visualization
- VS Code MCP integration

The result is an AI-to-GitHub infrastructure layer designed around **least privilege, observability, explicit authorization, and controlled execution**.

---

## Table of Contents

- [Why ContextBridge Exists](#why-contextbridge-exists)
- [Core Design Principles](#core-design-principles)
- [High-Level Architecture](#high-level-architecture)
- [End-to-End Request Flow](#end-to-end-request-flow)
- [Integrated AI Chat](#integrated-ai-chat)
- [MCP Server](#mcp-server)
- [GitHub Tooling](#github-tooling)
- [Read Operations](#read-operations)
- [Mutation Safety Architecture](#mutation-safety-architecture)
- [Human Approval Flow](#human-approval-flow)
- [Security Model](#security-model)
- [Telemetry and Audit Logging](#telemetry-and-audit-logging)
- [Evaluation Framework](#evaluation-framework)
- [Dashboard Control Plane](#dashboard-control-plane)
- [VS Code MCP Integration](#vs-code-mcp-integration)
- [Project Structure](#project-structure)
- [Installation](#installation)
- [Environment Configuration](#environment-configuration)
- [Running ContextBridge](#running-contextbridge)
- [Using the Chat Interface](#using-the-chat-interface)
- [Using ContextBridge from VS Code](#using-contextbridge-from-vs-code)
- [Available MCP Tools](#available-mcp-tools)
- [Safety Defaults](#safety-defaults)
- [Threat Model](#threat-model)
- [Example Workflows](#example-workflows)
- [Testing](#testing)
- [Design Decisions](#design-decisions)
- [Limitations](#limitations)
- [Roadmap](#roadmap)

---

## Why ContextBridge Exists

LLMs are increasingly capable of understanding source code, planning software changes, and operating external tools. The harder problem is how to let a model access real developer systems **without giving it excessive authority**.

A naive architecture often looks like this:

```mermaid
flowchart LR
    U[User] --> LLM[LLM]
    LLM --> TOKEN[GitHub Token]
    TOKEN --> GH[GitHub API]
```

This creates several problems:

- The model may be exposed too directly to credentials.
- Tool permissions may be broader than the user's actual request.
- Read and write capabilities can become difficult to separate.
- There may be no durable audit trail.
- A generated action can become an executed action without a human checkpoint.
- Prompt injection inside repository content may influence the model.
- There may be no consistent policy layer between reasoning and execution.

ContextBridge introduces a dedicated control boundary:

```mermaid
flowchart LR
    U[User] --> LLM[LLM / AI Assistant]
    LLM --> MCP[ContextBridge MCP Interface]
    MCP --> POLICY[Policy + Risk Controls]
    POLICY --> TOOLS[Scoped Tool Layer]
    TOOLS --> GH[GitHub API]

    MCP --> AUDIT[(Telemetry / Audit DB)]
    POLICY --> APPROVAL[Human Approval Layer]
```

The model can reason and request actions, but **ContextBridge owns execution**.

---

## Core Design Principles

### 1. Least Privilege

The model sees only explicitly exposed tools.

Read-only operations are separated from mutation-capable operations, and write execution remains gated by additional policy.

### 2. Human Authorization for Mutations

Potentially destructive or state-changing actions do not automatically become live GitHub operations.

The system can convert them into pending actions that require explicit human approval.

### 3. AI Cannot Self-Approve

Approval and rejection are intentionally kept outside the MCP tool surface.

The model can request an action, but it cannot approve its own request.

### 4. Dry-Run by Default

The default runtime posture is intentionally conservative:

```dotenv
CONTEXTBRIDGE_DRY_RUN=true
GITHUB_WRITES_ENABLED=false
```

This means mutation flows can be exercised without sending live GitHub write requests.

### 5. Auditability

Tool calls, results, durations, policy outcomes, chat sessions, and evaluation data can be persisted locally.

### 6. Provider Independence

The control plane is not tied to one LLM vendor.

ContextBridge supports provider abstraction for:

- Gemini
- OpenAI
- Ollama / local models

The model provider changes, but the MCP and safety architecture remain the same.

### 7. Repository Content Is Untrusted Data

Repository files, issues, comments, and other GitHub text are treated as data, not instructions.

This matters for reducing prompt-injection risk.

---

# High-Level Architecture

```mermaid
flowchart TB
    USER[User]

    subgraph CLIENTS[Client Layer]
        DASH[React Dashboard]
        VSCODE[VS Code MCP Client]
        OTHER[Other MCP-Compatible Clients]
    end

    subgraph APP[ContextBridge Application]
        API[FastAPI Control Plane]
        CHAT[Integrated Chat Orchestrator]
        MCP[MCP Server]
        POLICY[Policy Engine]
        RISK[Risk Classification]
        APPROVAL[Approval Manager]
        TELEMETRY[Telemetry + Audit]
        EVAL[Evaluation Engine]
    end

    subgraph MODELS[Model Providers]
        GEMINI[Google Gemini]
        OPENAI[OpenAI]
        OLLAMA[Ollama / Local Model]
    end

    subgraph DATA[Local State]
        SQLITE[(SQLite)]
        ENV[Environment Secrets]
    end

    GH[GitHub API]

    USER --> DASH
    USER --> VSCODE
    USER --> OTHER

    DASH --> API
    API --> CHAT
    CHAT --> GEMINI
    CHAT --> OPENAI
    CHAT --> OLLAMA

    GEMINI --> CHAT
    OPENAI --> CHAT
    OLLAMA --> CHAT

    CHAT --> MCP
    VSCODE --> MCP
    OTHER --> MCP

    MCP --> POLICY
    POLICY --> RISK
    POLICY --> APPROVAL
    POLICY --> GH

    MCP --> TELEMETRY
    CHAT --> TELEMETRY
    EVAL --> TELEMETRY

    TELEMETRY --> SQLITE
    APPROVAL --> SQLITE
    CHAT --> SQLITE

    ENV --> APP
```

---

# End-to-End Request Flow

A typical read-only request such as:

> "Inspect this repository and explain its architecture."

follows this path:

```mermaid
sequenceDiagram
    participant U as User
    participant UI as Dashboard / MCP Client
    participant M as LLM
    participant C as ContextBridge
    participant MCP as MCP Tool Layer
    participant GH as GitHub
    participant DB as SQLite

    U->>UI: Ask repository question
    UI->>M: Send prompt + available tools
    M->>UI: Request get_repository(...)
    UI->>C: Tool request
    C->>MCP: Validate tool + arguments
    MCP->>GH: GitHub API read
    GH-->>MCP: Repository metadata
    MCP->>DB: Log tool call
    MCP-->>UI: Tool result
    UI->>M: Return tool result
    M->>UI: Request get_file_contents(...)
    UI->>C: Tool request
    C->>GH: Fetch README/source
    GH-->>C: File contents
    C->>DB: Log call
    C-->>UI: Tool result
    UI->>M: Return result
    M-->>U: Final grounded answer
```

The key point is that the model does not directly call GitHub. It requests a named ContextBridge tool, and ContextBridge performs the operation.

---

# Integrated AI Chat

ContextBridge includes a local chat interface inside the dashboard.

The chat system combines:

- persistent conversations
- configurable LLM provider
- dynamic MCP tool discovery
- model-selected tool calls
- read-only mode
- tool execution timeline
- local chat persistence
- credential isolation
- MCP-based repository access

## Chat Architecture

```mermaid
flowchart LR
    USER[User] --> REACT[React Chat UI]
    REACT --> API[FastAPI]
    API --> CHAT[Chat Orchestrator]

    CHAT --> MODEL[Gemini / OpenAI / Ollama]
    MODEL -->|Function Call| CHAT

    CHAT --> MCP[MCP Client]
    MCP --> SERVER[ContextBridge MCP Server]
    SERVER --> GH[GitHub]

    GH --> SERVER
    SERVER --> MCP
    MCP --> CHAT

    CHAT -->|Function Result| MODEL
    MODEL -->|Final Answer| CHAT
    CHAT --> REACT

    CHAT --> DB[(SQLite)]
```

## Why Tool Execution Is Manual

LLM SDKs can often execute Python functions automatically. ContextBridge deliberately avoids delegating tool execution directly to the SDK.

The model may choose:

```text
get_repository
```

with arguments such as:

```json
{
  "owner": "example-user",
  "repo": "example-repo"
}
```

But ContextBridge itself executes the tool.

This ensures that every tool call still passes through:

- MCP
- read-only restrictions
- risk classification
- telemetry
- mutation policy
- approval requirements
- dry-run controls

The model provider therefore remains a **reasoning layer**, not the authority layer.

---

# MCP Server

ContextBridge exposes its capabilities through the **Model Context Protocol**.

The MCP server acts as the standardized interface between AI clients and controlled developer tooling.

```mermaid
flowchart LR
    CLIENT[MCP Client]
    SERVER[ContextBridge MCP Server]
    TOOLREG[Tool Registry]
    POLICY[Policy Layer]
    BACKEND[GitHub + Local Services]

    CLIENT --> SERVER
    SERVER --> TOOLREG
    TOOLREG --> POLICY
    POLICY --> BACKEND
```

This enables ContextBridge to work with more than its own dashboard.

An MCP-compatible client can discover available tools dynamically and invoke them using the standard protocol.

---

# GitHub Tooling

ContextBridge's GitHub integration is divided into two broad categories:

```mermaid
flowchart TB
    GH[GitHub Tools]

    GH --> READ[Read Tools]
    GH --> MUT[Mutation Requests]

    READ --> R1[Repository Metadata]
    READ --> R2[Files]
    READ --> R3[Issues]
    READ --> R4[Pull Requests]
    READ --> R5[Commits]
    READ --> R6[Code Search]
    READ --> R7[Workflow Runs]
    READ --> R8[Commit Status]

    MUT --> M1[Create Issue]
    MUT --> M2[Add Comment]
    MUT --> M3[Add Labels]
    MUT --> M4[Close Issue]
    MUT --> M5[Reopen Issue]
```

---

# Read Operations

Read tools are intended for repository inspection, code understanding, debugging, research, and developer assistance.

Examples include:

- listing repositories
- reading repository metadata
- reading files
- searching code
- searching issues
- reading issue details
- listing pull requests
- reading pull requests
- listing commits
- checking CI/workflow runs
- checking commit status

These tools are suitable for tasks such as:

> "Explain what this repository does."

> "Find where authentication is implemented."

> "Summarize open issues related to deployment."

> "Inspect the README and source tree and explain the architecture."

> "Find which workflow is failing."

---

# Mutation Safety Architecture

Mutation-capable tools are handled differently from read tools.

A requested mutation is not automatically equivalent to a live GitHub API write.

```mermaid
flowchart TD
    MODEL[Model Requests Mutation]
    VALIDATE[Validate Tool + Arguments]
    RISK[Classify Risk]
    POLICY{Policy Allows Request?}
    PENDING[Create Signed Pending Action]
    HUMAN{Human Decision}
    REJECT[Reject]
    APPROVE[Approve]
    CLAIM[One-Time Execution Claim]
    DRY{Dry Run?}
    SIM[Simulate Execution]
    WRITE{GitHub Writes Enabled?}
    ALLOW{Repository Allowlisted?}
    GH[Send GitHub Mutation]
    AUDIT[Persist Audit Result]

    MODEL --> VALIDATE
    VALIDATE --> RISK
    RISK --> POLICY

    POLICY -->|No| AUDIT
    POLICY -->|Confirmation Required| PENDING

    PENDING --> HUMAN

    HUMAN -->|Reject| REJECT
    HUMAN -->|Approve| APPROVE

    REJECT --> AUDIT
    APPROVE --> CLAIM
    CLAIM --> DRY

    DRY -->|Yes| SIM
    SIM --> AUDIT

    DRY -->|No| WRITE
    WRITE -->|No| AUDIT
    WRITE -->|Yes| ALLOW

    ALLOW -->|No| AUDIT
    ALLOW -->|Yes| GH

    GH --> AUDIT
```

This structure allows mutation workflows to be tested end-to-end without granting the model unrestricted write capability.

---

# Human Approval Flow

Pending actions are persisted locally.

A pending action contains information such as:

- action ID
- requested tool
- arguments
- risk level
- creation time
- expiry
- decision state
- integrity signature

The approval path is intentionally separate from MCP:

```mermaid
flowchart LR
    AI[AI / MCP] --> REQUEST[Mutation Request]
    REQUEST --> PENDING[(Pending Action)]
    PENDING --> LOCAL[Local Dashboard / CLI]
    LOCAL --> HUMAN[Human]
    HUMAN -->|Approve| SIGNED[Signed Approval]
    HUMAN -->|Reject| DENIED[Rejected]
    SIGNED --> EXEC[Controlled Execution]
```

The AI does **not** receive an MCP tool such as:

```text
approve_pending_action
```

That omission is intentional.

It prevents a model from generating an action and then immediately granting itself permission to execute it.

---

# Security Model

ContextBridge's security model is layered rather than dependent on one switch.

## Layer 1: Secret Isolation

Secrets remain in local environment configuration.

Examples:

```dotenv
GITHUB_TOKEN=...
GEMINI_API_KEY=...
OPENAI_API_KEY=...
```

The browser does not need access to these values.

The dashboard receives only non-secret provider state such as:

```json
{
  "provider": "gemini",
  "model": "gemini-3.6-flash",
  "configured": true
}
```

## Layer 2: Tool Surface Restriction

The model can only call registered MCP tools.

It does not receive a generic unrestricted shell or arbitrary GitHub HTTP tool.

## Layer 3: Read-Only Mode

Integrated chat can expose only read-classified tools.

```mermaid
flowchart LR
    MODEL[Model]
    FILTER{Read-Only Enabled?}
    READ[Expose Read Tools]
    ALL[Expose Allowed Tool Set]

    MODEL --> FILTER
    FILTER -->|Yes| READ
    FILTER -->|No| ALL
```

## Layer 4: Risk Classification

Tools are assigned risk semantics so that policy can distinguish reads from mutations.

## Layer 5: Confirmation

Sensitive operations can require human confirmation.

## Layer 6: Signed Actions

Pending actions and approvals are integrity-protected.

## Layer 7: One-Time Execution

An approved action must be claimed for execution so the same approval cannot be freely replayed.

## Layer 8: Dry Run

Even an approved action can remain simulated.

## Layer 9: Write Disable Switch

```dotenv
GITHUB_WRITES_ENABLED=false
```

provides a separate global write gate.

## Layer 10: Repository Allowlisting

If live mutations are ever enabled, they can be constrained to explicitly authorized repositories.

---

# Telemetry and Audit Logging

ContextBridge records operational information in SQLite.

The telemetry system provides visibility into:

- which tool was called
- when it was called
- arguments
- result status
- duration
- error state
- risk classification
- policy outcome
- chat session association
- evaluation results

```mermaid
flowchart LR
    MCP[MCP Tool Call] --> REC[Telemetry Recorder]
    CHAT[Chat Tool Call] --> REC
    POLICY[Policy Decision] --> REC
    EVAL[Evaluation Run] --> REC

    REC --> DB[(SQLite)]

    DB --> DASH[Dashboard]
    DB --> AUDIT[Audit Queries]
    DB --> METRICS[Metrics]
```

Sensitive fields are redacted where appropriate before persistence or display.

---

# Evaluation Framework

ContextBridge includes a deterministic evaluation layer for validating tool routing behavior.

The evaluation framework can measure:

- tool-selection accuracy
- argument/parameter accuracy
- risk classification accuracy
- mutation classification accuracy

Conceptually:

```mermaid
flowchart LR
    CASES[Evaluation Cases]
    ROUTER[Tool Selection Logic]
    RESULT[Predicted Tool + Params]
    EXPECTED[Expected Result]
    SCORE[Scoring Engine]
    DB[(SQLite)]

    CASES --> ROUTER
    ROUTER --> RESULT
    RESULT --> SCORE
    EXPECTED --> SCORE
    SCORE --> DB
```

The purpose is to make tool behavior measurable instead of relying only on ad-hoc manual testing.

---

# Dashboard Control Plane

ContextBridge includes a local React/FastAPI dashboard.

Default address:

```text
http://127.0.0.1:8765
```

The dashboard provides a control plane for:

- operational overview
- integrated AI chat
- pending approvals
- audit history
- evaluations
- tool catalog
- security posture

```mermaid
flowchart TB
    REACT[React UI]
    FASTAPI[FastAPI Backend]

    REACT --> FASTAPI

    FASTAPI --> CHAT[Chat Service]
    FASTAPI --> DB[(SQLite)]
    FASTAPI --> POLICY[Policy State]
    FASTAPI --> TOOLS[MCP Tool Catalog]
    FASTAPI --> EVAL[Evaluation Results]
```

The dashboard is designed primarily as a **local control plane**, not as a public web application.

---

# VS Code MCP Integration

ContextBridge can also run as an MCP server directly inside VS Code.

Example `.vscode/mcp.json` configuration:

```json
{
  "servers": {
    "contextbridge": {
      "type": "stdio",
      "command": "${workspaceFolder}/.venv/Scripts/python.exe",
      "args": ["-m", "contextbridge.server"],
      "cwd": "${workspaceFolder}",
      "envFile": "${workspaceFolder}/.env"
    }
  }
}
```

The flow becomes:

```mermaid
flowchart LR
    DEV[Developer]
    VSCODE[VS Code AI / Agent]
    MCP[ContextBridge MCP Server]
    GH[GitHub]

    DEV --> VSCODE
    VSCODE --> MCP
    MCP --> GH
    GH --> MCP
    MCP --> VSCODE
```

---

# Project Structure

A typical repository layout is:

```text
ContextBridge/
│
├── src/
│   └── contextbridge/
│       ├── server.py
│       ├── config.py
│       ├── chat.py
│       ├── dashboard.py
│       ├── dashboard_static/
│       ├── github/
│       ├── security/
│       ├── telemetry/
│       ├── evaluation/
│       └── tools/
│
├── dashboard/
├── docs/
├── evals/
├── scripts/
├── tests/
├── .env.example
├── .gitignore
├── pyproject.toml
├── README.md
├── SECURITY.md
└── CHANGELOG.md
```

---

# Installation

## Requirements

Recommended environment:

- Python 3.12+
- Git
- Windows PowerShell for the included Windows scripts
- GitHub account/token
- Optional Gemini, OpenAI, or Ollama configuration

Clone the repository:

```powershell
git clone https://github.com/Vatsal212005/ContextBridge.git
cd ContextBridge
```

For a fresh Windows setup:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_windows.ps1
```

---

# Environment Configuration

Create `.env` from `.env.example`.

Example:

```dotenv
# GitHub
GITHUB_TOKEN=

# Runtime safety
CONTEXTBRIDGE_DRY_RUN=true
GITHUB_WRITES_ENABLED=false
GITHUB_WRITE_REPOSITORIES=

# Integrated chat provider
CONTEXTBRIDGE_LLM_PROVIDER=gemini
CONTEXTBRIDGE_LLM_MODEL=gemini-3.6-flash

# Gemini
GEMINI_API_KEY=

# OpenAI
OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com

# Ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_API_KEY=

# Chat behavior
CONTEXTBRIDGE_CHAT_MAX_TOOL_ROUNDS=8
CONTEXTBRIDGE_CHAT_HISTORY_MESSAGES=30
CONTEXTBRIDGE_CHAT_READ_ONLY_DEFAULT=true
```

Never commit `.env`.

The repository should commit only `.env.example` with blank or placeholder values.

---

# Running ContextBridge

## Start the Dashboard

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

Then open:

```text
http://127.0.0.1:8765
```

## Start the MCP Server Directly

```powershell
.\.venv\Scripts\python.exe -m contextbridge.server
```

The server uses MCP over stdio for compatible clients.

---

# Using the Chat Interface

Open the dashboard and select **Chat**.

A useful first prompt is:

> Inspect `Vatsal212005/FeatureForge`. Read the repository metadata, README, and relevant source files. Explain what the project does, its architecture, major components, and how they interact. Do not modify anything.

With read-only mode enabled, the model can inspect GitHub data but cannot request mutation tools through the chat surface.

---

# Available MCP Tools

## System

- `server_info`
- `health`
- `github_connection_status`

## GitHub Read Tools

- `list_repositories`
- `get_repository`
- `get_file_contents`
- `search_code`
- `search_issues`
- `get_issue`
- `list_pull_requests`
- `get_pull_request`
- `list_commits`
- `get_workflow_runs`
- `get_commit_status`

## Telemetry and Evaluation

- `get_tool_metrics`
- `get_recent_tool_calls`
- `get_audit_summary`
- `get_evaluation_summary`

## Policy and Pending Actions

- `get_write_policy`
- `list_pending_actions`
- `get_pending_action`
- `execute_approved_action`

## Mutation Request Tools

- `create_issue`
- `add_issue_comment`
- `add_labels`
- `close_issue`
- `reopen_issue`

These tools do not imply unrestricted live execution. Their behavior is governed by the mutation safety architecture.

---

# Safety Defaults

ContextBridge is intentionally conservative by default.

```dotenv
CONTEXTBRIDGE_DRY_RUN=true
GITHUB_WRITES_ENABLED=false
CONTEXTBRIDGE_CHAT_READ_ONLY_DEFAULT=true
```

Under this posture:

- GitHub reads can operate normally.
- The chat interface defaults to read-only.
- Mutation flows can be represented and audited.
- Live GitHub write execution remains disabled.

---

# Threat Model

ContextBridge is designed around several practical AI-tooling threats.

## Prompt Injection in Repository Content

Repository text can contain hostile or misleading instructions. ContextBridge treats that content as untrusted data and keeps execution behind a separate policy boundary.

## Model Hallucination

For GitHub-dependent claims, the system is designed to retrieve current repository state through tools instead of relying only on model memory.

## Credential Leakage

Credentials remain server-side in environment configuration and are not intentionally returned through dashboard APIs.

## Unauthorized Mutations

Mutation flows can require confirmation and remain globally disabled by default.

## Self-Approval

The model is not given approval tools.

## Replay of Approved Actions

Approved execution is tracked as a controlled, one-time claim rather than a reusable permission.

## Scope Expansion

Future live-write deployments can combine repository allowlisting with separately scoped GitHub credentials.

---

# Example Workflows

## Repository Understanding

```mermaid
flowchart LR
    Q[User asks what repo does]
    META[get_repository]
    README[get_file_contents README]
    CODE[search_code / source reads]
    ANSWER[Architecture explanation]

    Q --> META
    META --> README
    README --> CODE
    CODE --> ANSWER
```

## CI Investigation

```mermaid
flowchart LR
    Q[User asks why build failed]
    RUNS[get_workflow_runs]
    COMMIT[get_commit_status]
    CODE[get_file_contents]
    ANALYZE[Model analysis]
    RESULT[Suggested fix]

    Q --> RUNS
    RUNS --> COMMIT
    COMMIT --> CODE
    CODE --> ANALYZE
    ANALYZE --> RESULT
```

## Safe Mutation Request

```mermaid
flowchart TD
    U[User requests GitHub change]
    M[Model selects mutation tool]
    C[ContextBridge receives request]
    P[Policy evaluation]
    A[Pending action]
    H[Human review]
    D{Approved?}
    SIM[Dry-run / controlled execution]
    BLOCK[Rejected / blocked]

    U --> M
    M --> C
    C --> P
    P --> A
    A --> H
    H --> D
    D -->|Yes| SIM
    D -->|No| BLOCK
```

---

# Testing

Run the full Python test suite with:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

The project also includes targeted verification for:

- MCP connectivity
- dashboard APIs
- integrated chat persistence
- provider configuration
- safety posture
- evaluation behavior

---

# Design Decisions

## Why MCP?

MCP creates a standardized boundary between AI clients and developer tools. ContextBridge can therefore expose the same controlled capabilities to multiple MCP-compatible clients.

## Why SQLite?

SQLite is appropriate for a local-first control plane because it provides transactional structured persistence without requiring a separate database service.

## Why Local Approval?

Keeping approval outside the model-facing tool surface prevents a model from turning its own mutation request into authorization.

## Why Multiple LLM Providers?

The model should be replaceable without redesigning the security architecture. Authority belongs to ContextBridge, not to the provider.

## Why Explicit Tool Calls?

Explicit tool calls are easier to inspect, audit, classify, test, and govern than an opaque agent with unrestricted network access.

---

# Limitations

ContextBridge is intentionally conservative.

Current tradeoffs include:

- The dashboard is primarily intended for local use.
- Live mutation execution should only be enabled with carefully scoped credentials and repository restrictions.
- Model output quality depends on the selected provider.
- Prompt injection is mitigated through defense in depth rather than assumed to be fully solved.
- Large repositories may require iterative tool calls instead of loading the entire codebase at once.

---

# Roadmap

Potential future directions include:

- stronger repository-scoped authorization policies
- richer approval policies by risk level
- additional GitHub mutation types
- finer-grained credential separation
- more MCP clients
- improved prompt-injection defenses
- richer code-graph analysis
- semantic repository indexing
- local embeddings
- repository dependency visualization
- tool-call replay and debugging
- policy simulation
- RBAC for shared deployments
- containerized deployment profiles
- richer evaluation suites
- model/provider benchmarking
- streaming model output
- organization-level GitHub policy support

---

# Security Notes

Do not commit:

```text
.env
GitHub tokens
Gemini API keys
OpenAI API keys
SQLite runtime databases
signing keys
private certificates
local chat history
```

Use `.env.example` for configuration documentation.

If a credential is accidentally committed, deleting it in a later commit is not enough because it may remain in Git history. Revoke and rotate the credential immediately.

---

# Summary

ContextBridge separates **AI reasoning** from **system authority**.

The model can decide that it wants to inspect a file or request an action, but the infrastructure decides whether that operation exists, whether it is allowed, whether it requires confirmation, and whether it can actually execute.

```mermaid
flowchart LR
    REASON[AI Reasoning]
    REQUEST[Structured Tool Request]
    CONTROL[ContextBridge Control Boundary]
    AUTH[Authorization + Policy]
    EXEC[Execution]
    AUDIT[Audit]

    REASON --> REQUEST
    REQUEST --> CONTROL
    CONTROL --> AUTH
    AUTH --> EXEC
    CONTROL --> AUDIT
    EXEC --> AUDIT
```

That separation is the central idea behind ContextBridge:

> **Give AI useful access to developer systems without giving it unrestricted control over them.**
