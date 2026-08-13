# Architecture and trust boundaries

## Trust boundaries

1. **AI/MCP boundary** — the model can only invoke registered semantic MCP tools. It cannot call a
   raw arbitrary GitHub endpoint and cannot approve/reject pending actions.
2. **Policy boundary** — mutation requests are classified as write/destructive and persisted as
   exact signed pending actions before any future GitHub mutation path is considered.
3. **Human boundary** — approval/rejection exists only in the local CLI and local dashboard.
4. **GitHub boundary** — read operations use the fine-grained credential. Live mutation execution
   remains disabled in v0.8 because Milestone 6B was skipped.
5. **Observability boundary** — execution arguments are redacted before persistence; audit events
   are database-enforced append-only.

## Mutation lifecycle

```text
requested -> pending -> approved -> executing -> simulated (v0.8)
                  \-> rejected
pending -----------> expired
```

Approval signatures bind the human decision to the exact action record. Execution claims are
atomic and single-use, preventing an approved action from being replayed twice.

## Dashboard

The dashboard is a separate FastAPI control plane serving a prebuilt React UI. It is not an MCP
resource/tool. Localhost is the default bind target. Non-loopback binding fails closed unless a
separate dashboard token is configured.
