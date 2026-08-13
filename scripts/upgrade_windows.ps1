$ErrorActionPreference = "Stop"
Write-Host "ContextBridge v0.9.1 - native Gemini integrated-chat upgrade (6B still skipped)"

function Read-EnvTextWithRetry {
    $envPath = (Resolve-Path .env).Path
    $lastError = $null
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try { return [System.IO.File]::ReadAllText($envPath) }
        catch { $lastError = $_; Start-Sleep -Milliseconds (250 * $attempt) }
    }
    throw "Could not read .env after multiple retries. Close any editor holding .env, pause OneDrive sync briefly, then retry. Last error: $lastError"
}

function Write-EnvTextWithRetry {
    param([Parameter(Mandatory=$true)][AllowEmptyString()][string]$Text)
    $envPath = (Resolve-Path .env).Path
    $encoding = New-Object System.Text.UTF8Encoding($false)
    $lastError = $null
    for ($attempt = 1; $attempt -le 8; $attempt++) {
        try {
            $tmp = $envPath + ".contextbridge.tmp"
            [System.IO.File]::WriteAllText($tmp, $Text, $encoding)
            [System.IO.File]::Copy($tmp, $envPath, $true)
            Remove-Item $tmp -Force -ErrorAction SilentlyContinue
            return
        }
        catch { $lastError = $_; Start-Sleep -Milliseconds (250 * $attempt) }
    }
    throw "Could not update .env after multiple retries. Close any editor holding .env, pause OneDrive sync briefly, then retry. Last error: $lastError"
}

function Set-EnvValueSafely {
    param([Parameter(Mandatory=$true)][string]$Name,[Parameter(Mandatory=$true)][AllowEmptyString()][string]$Value)
    $text = Read-EnvTextWithRetry
    $pattern = "(?m)^\s*" + [regex]::Escape($Name) + "\s*=.*$"
    $line = "$Name=$Value"
    if ([regex]::IsMatch($text, $pattern)) {
        $text = [regex]::Replace($text, $pattern, [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $line })
    } else {
        if ($text.Length -gt 0 -and -not $text.EndsWith([Environment]::NewLine)) { $text += [Environment]::NewLine }
        $text += $line + [Environment]::NewLine
    }
    Write-EnvTextWithRetry $text
}

function Get-EnvValue {
    param([Parameter(Mandatory=$true)][string]$Name)
    $text = Read-EnvTextWithRetry
    $match = [regex]::Match($text, "(?m)^\s*" + [regex]::Escape($Name) + "\s*=\s*(.*)\s*$")
    if (-not $match.Success) { return $null }
    return $match.Groups[1].Value.Trim()
}

if (-not (Test-Path .\.venv\Scripts\python.exe)) { throw ".venv was not found. Run scripts\setup_windows.ps1 once before using the upgrade script." }
if (-not (Test-Path .env)) { Copy-Item .env.example .env; Write-Host "Created .env from .env.example" }
else { Write-Host "Keeping existing .env (GitHub token, SQLite history path, signing settings, and any existing model keys)" }

# v0.9.1 does not activate 6B or any live GitHub write path.
if ($null -eq (Get-EnvValue "CONTEXTBRIDGE_DRY_RUN")) { Set-EnvValueSafely "CONTEXTBRIDGE_DRY_RUN" "true" }
if ($null -eq (Get-EnvValue "GITHUB_WRITES_ENABLED")) { Set-EnvValueSafely "GITHUB_WRITES_ENABLED" "false" }
$dryRun = Get-EnvValue "CONTEXTBRIDGE_DRY_RUN"
$writesEnabled = Get-EnvValue "GITHUB_WRITES_ENABLED"
if ($null -eq $dryRun -or $dryRun.ToLowerInvariant() -ne "true") { throw "Safety preflight failed: CONTEXTBRIDGE_DRY_RUN must remain true for this upgrade." }
if ($null -eq $writesEnabled -or $writesEnabled.ToLowerInvariant() -ne "false") { throw "Safety preflight failed: GITHUB_WRITES_ENABLED must remain false for this upgrade." }

# Switch the integrated dashboard chat to Gemini while preserving any existing
# OpenAI/Ollama keys so the user can switch providers later.
Set-EnvValueSafely "CONTEXTBRIDGE_LLM_PROVIDER" "gemini"
Set-EnvValueSafely "CONTEXTBRIDGE_LLM_MODEL" "gemini-3.6-flash"
if ($null -eq (Get-EnvValue "GEMINI_API_KEY")) { Set-EnvValueSafely "GEMINI_API_KEY" ""; Write-Host "Added GEMINI_API_KEY=" }

Write-Host "Configured dashboard chat provider: gemini / gemini-3.6-flash"
Write-Host "Safety preflight: DRY_RUN=true, GitHub writes disabled"
Write-Host "Keeping existing .venv, SQLite history, GitHub token, pending actions, and signing key"

& .\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Write-Host ""; Write-Host "Running full test suite..."
& .\.venv\Scripts\python.exe -m pytest
Write-Host ""; Write-Host "Running MCP smoke test..."
& .\.venv\Scripts\python.exe scripts\smoke_test.py
Write-Host ""; Write-Host "Running Gemini provider check (no model/API request)..."
& .\.venv\Scripts\python.exe scripts\gemini_check.py
Write-Host ""; Write-Host "Running integrated-chat persistence check..."
& .\.venv\Scripts\python.exe scripts\chat_check.py
Write-Host ""; Write-Host "Running dashboard regression check..."
& .\.venv\Scripts\python.exe scripts\dashboard_check.py

Write-Host ""
Write-Host "Upgrade complete. ContextBridge is now v0.9.1 with native Gemini chat support."
Write-Host "Milestone 6B remains skipped: DRY_RUN=true and GitHub writes are disabled."
Write-Host ""
Write-Host "Next: put your Google AI Studio key after GEMINI_API_KEY= in .env."
Write-Host "Then restart the dashboard with:"
Write-Host "  powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1"
Write-Host "Open http://127.0.0.1:8765 and select Chat."
