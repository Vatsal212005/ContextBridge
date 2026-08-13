# ContextBridge evaluation harness

`tool_selection.json` contains **100 provider-agnostic benchmark prompts** covering GitHub read tools,
mutation routing, observability, human-confirmation operations, and evaluation introspection.

The built-in baseline is a deterministic keyword router. It exists to verify the benchmark and
scoring pipeline; **do not present its score as an LLM score**.

Run the baseline and persist the result to the existing ContextBridge SQLite database:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py --baseline
```

To evaluate a real model/MCP host, export one JSON object per case:

```json
[
  {
    "id": "get_repository-01",
    "actual_tool": "get_repository",
    "actual_arguments": {"owner": "Vatsal212005", "repo": "FeatureForge"}
  }
]
```

Then run:

```powershell
.\.venv\Scripts\python.exe scripts\run_evals.py --predictions evals\my_predictions.json
```

Metrics include tool-selection accuracy, partial parameter accuracy, risk classification accuracy,
mutation/confirmation classification accuracy, per-tool accuracy, and top confusions. Runs are
persisted in `evaluation_runs` and `evaluation_results` and appear in the dashboard.
