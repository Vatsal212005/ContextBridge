# Upgrade to ContextBridge v0.9.0

This upgrade adds integrated conversational MCP chat to the existing local React dashboard.

## Preserved

The upgrade does not include or replace `.env`, `.venv`, the SQLite runtime database, the pending-action signing key, or any GitHub credentials. The Windows upgrade script refuses to proceed if dry-run has been disabled or GitHub live writes have been enabled.

## Install on the existing Windows checkout

1. Extract this archive directly over the existing `contextbridge` directory and overwrite matching project files.
2. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade_windows.ps1
```

3. Configure one provider in `.env`.

OpenAI:

```dotenv
CONTEXTBRIDGE_LLM_PROVIDER=openai
CONTEXTBRIDGE_LLM_MODEL=gpt-5-mini
OPENAI_API_KEY=...
```

Or local Ollama:

```dotenv
CONTEXTBRIDGE_LLM_PROVIDER=ollama
CONTEXTBRIDGE_LLM_MODEL=qwen3:8b
OLLAMA_BASE_URL=http://127.0.0.1:11434
```

4. Restart the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

5. Open `http://127.0.0.1:8765` and choose **Chat**.

Chat defaults to read-only mode. Milestone 6B is still not enabled.
