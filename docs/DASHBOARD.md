# Local React dashboard

Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

Open `http://127.0.0.1:8765`.

The UI is prebuilt under `src/contextbridge/dashboard_static`; Node/npm is not needed at runtime.
React source is retained in `frontend/src/main.tsx`.

## Approval behavior

Approving or rejecting an action in the browser calls only the local dashboard API. The endpoint
requires the exact confirmation word (`APPROVE` / `REJECT`) and delegates to the same signed-action
store used by the CLI. No approval endpoint is registered as an MCP tool.

## Remote binding

The dashboard refuses a non-loopback bind unless `CONTEXTBRIDGE_DASHBOARD_TOKEN` is non-empty. Keep
it on localhost for normal development.
