# Upgrade to ContextBridge v0.9.1 — Gemini

This is an in-place upgrade from v0.9.0. It preserves `.venv`, `.env`, your GitHub token, SQLite history, pending actions, and action-signing key.

## What changes

- Adds the official `google-genai` Python SDK.
- Adds `gemini` as a first-class integrated-chat provider.
- Defaults the dashboard chat to `gemini-3.6-flash`.
- Keeps OpenAI and Ollama available.
- Keeps 6B disabled (`CONTEXTBRIDGE_DRY_RUN=true`, `GITHUB_WRITES_ENABLED=false`).

## Upgrade

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade_windows.ps1
```

Then put your Google AI Studio API key in `.env`:

```dotenv
GEMINI_API_KEY=your_key_here
```

Restart the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

The Chat page should report `gemini · gemini-3.6-flash`.
