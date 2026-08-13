# Security policy

## v0.8 safety invariants

- Live GitHub writes are disabled by default and by the upgrade preflight.
- No repository deletion, content-write, branch-delete, force-push, merge, settings, or workflow
  mutation capability is implemented.
- Every issue mutation request becomes a signed pending action.
- Approval/rejection is absent from the MCP surface.
- Approvals expire and are single-use.
- Audit records are append-only at the SQLite trigger layer.
- Secret-like fields are redacted before telemetry persistence.
- Dashboard binds to loopback by default and requires a token for non-loopback binding.

Do not commit `.env`, the SQLite database, or the local `.action-key` file.


## Integrated chat (v0.9)

Model and GitHub credentials remain server-side. The browser receives only provider/model metadata and
redacted operational results. Chat defaults to read-only tool exposure. Tool-returned repository text is
explicitly treated as untrusted data in the model instructions. Hosted LLM providers necessarily receive
the repository snippets/tool results needed to answer a question; users who require fully local inference
should use the Ollama provider. OpenAI Responses requests set `store=false` and manually carry forward
function-call state for the active turn.
