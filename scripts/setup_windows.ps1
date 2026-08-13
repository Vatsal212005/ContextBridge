$ErrorActionPreference = "Stop"

Write-Host "ContextBridge v0.8.0 - first-time Windows setup"

function Add-EnvLineSafely {
    param([Parameter(Mandatory=$true)][string]$Line)
    $envPath = (Resolve-Path .env).Path
    $encoding = New-Object System.Text.UTF8Encoding($false)
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try { [System.IO.File]::AppendAllText($envPath, $Line + [Environment]::NewLine, $encoding); return }
        catch { Start-Sleep -Milliseconds (250 * $attempt); if ($attempt -eq 8) { throw } }
    }
}

if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python launcher 'py' was not found. Install Python 3.12+ and try again."
}

if (-not (Test-Path .\.venv\Scripts\python.exe)) {
    py -3.12 -m venv .venv
} else {
    Write-Host "Existing .venv detected; keeping it."
}

& .\.venv\Scripts\python.exe -m pip install --upgrade pip
& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

if (-not (Test-Path .env)) { Copy-Item .env.example .env } else { Write-Host "Existing .env detected; keeping it." }

if (-not (Select-String -Path .env -Pattern '^CONTEXTBRIDGE_DB_PATH=' -Quiet)) {
    $dbDir = Join-Path $env:LOCALAPPDATA "ContextBridge"
    $dbPath = Join-Path $dbDir "contextbridge.db"
    New-Item -ItemType Directory -Force $dbDir | Out-Null
    Add-EnvLineSafely ""
    Add-EnvLineSafely "CONTEXTBRIDGE_DB_PATH=$dbPath"
    Write-Host "Configured SQLite telemetry at $dbPath"
}

Write-Host ""
Write-Host "Running tests..."
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe scripts\smoke_test.py
& .\.venv\Scripts\python.exe scripts\evaluation_check.py
& .\.venv\Scripts\python.exe scripts\dashboard_check.py

Write-Host ""
Write-Host "Setup complete."
Write-Host "MCP stdio: .\.venv\Scripts\contextbridge.exe"
Write-Host "Inspector: .\.venv\Scripts\mcp.exe dev src\contextbridge\server.py"
Write-Host "Dashboard: powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1"
