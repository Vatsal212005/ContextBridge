$ErrorActionPreference = "Stop"
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    throw ".venv was not found. Run the ContextBridge setup/upgrade first."
}
Write-Host "Starting ContextBridge local dashboard on http://127.0.0.1:8765"
Write-Host "Press Ctrl+C to stop it."
& .\.venv\Scripts\python.exe -m contextbridge.dashboard
