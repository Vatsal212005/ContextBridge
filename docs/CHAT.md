# Integrated Chat

ContextBridge v0.9 embeds the conversational client into the local dashboard.

```text
Browser (React)
    │ POST /api/chat/.../stream
    ▼
Local FastAPI control plane
    │
    ├─ model provider (Gemini, OpenAI Responses API, or Ollama)
    │
    └─ MCP Client
          │
          ▼
       ContextBridge MCPServer
          │
          ▼
        GitHub
```

The model is never allowed to invoke dashboard approval/rejection endpoints. Those endpoints remain on
the local human control plane, outside the MCP tool surface.

## Read-only default

Each chat starts with read-only mode enabled. Only read-classified MCP tools are exposed to the model.
If the user disables read-only mode, mutation request tools may be selected, but they still enter the
signed pending-action confirmation flow and remain dry-run while Milestone 6B is disabled.

## Streaming

The browser uses a POST endpoint that returns Server-Sent Events. Events include status updates,
tool-start/tool-end records, a final answer, and errors. Model token streaming is intentionally not yet
relayed token-by-token; the visible stream focuses on tool orchestration and final answer completion.


## Gemini provider

Set `CONTEXTBRIDGE_LLM_PROVIDER=gemini`, `CONTEXTBRIDGE_LLM_MODEL=gemini-3.6-flash`, and provide `GEMINI_API_KEY`. Gemini tool calls are manually executed through the same internal MCP path used by the other providers, so ContextBridge remains the enforcement point for read-only mode, policy, telemetry, and human confirmation.
