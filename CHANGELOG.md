
## v0.9.1 hotfix
- Fixed Gemini manual function-response serialization: `Part.from_function_response()` is now called with the supported `name` and `response` arguments only.
- Added a regression test for Gemini MCP tool-result round-tripping.
- Updated stale v0.9.0/schema-v3 test expectations to v0.9.1/schema v4.

# v0.9.1

- Added native Google Gemini provider support through the official `google-genai` 2.x SDK.
- Added manual Gemini function-calling orchestration through the existing ContextBridge MCP client, preserving telemetry, read-only filtering, risk policy, signed approvals, and dry-run safety.
- Set Gemini 3.6 Flash as the default integrated-chat model for new installs/upgrades.
- Kept OpenAI and Ollama provider support intact.
- Added Gemini configuration validation and dashboard credential-leak regression coverage.
- Milestone 6B remains disabled; live GitHub writes are still off by default.

# v0.9.0

- Added integrated React dashboard Chat page with persistent conversations.
- Added server-side OpenAI Responses API and Ollama provider adapters.
- Added a real in-process MCP client loop for model-selected ContextBridge tools.
- Added read-only-by-default chat tool exposure.
- Added SSE progress for tool calls and final answers.
- Added SQLite chat_sessions, chat_messages, and chat_tool_calls (schema v4).
- Kept credentials server-side and added chat/tool timeline persistence with redaction.
- Preserved Milestone 6A safety; live GitHub writes remain disabled.

# Changelog

## 0.8.0 — Milestone 8

- Added 100-case provider-agnostic tool-selection benchmark.
- Added tool, parameter, risk, and mutation-classification metrics.
- Added SQLite `evaluation_runs` and `evaluation_results` with schema migration v2 -> v3.
- Added `get_evaluation_summary` read-only MCP tool (27 tools total).
- Added local FastAPI control plane and prebuilt React dashboard.
- Added dashboard human approval/rejection without exposing approval through MCP.
- Added localhost-only dashboard default and non-loopback token fail-closed behavior.
- Added evaluation/dashboard tests and verification scripts.
- Preserved Milestone 6B as intentionally disabled: dry-run true, GitHub writes false.
