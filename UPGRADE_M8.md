# Upgrade to Milestone 8

This upgrade assumes ContextBridge Milestone 7 (v0.7.0) is already installed.

It preserves your existing `.env`, `.venv`, SQLite history, GitHub token, pending actions,
and local action-signing key. Milestone 6B remains intentionally skipped: live GitHub writes
must stay disabled during this upgrade.

## Windows

1. Extract this ZIP directly over your existing ContextBridge folder.
2. Choose **Replace/Overwrite** for matching files.
3. Run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\upgrade_windows.ps1
```

4. After the checks pass, start the dashboard:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_dashboard.ps1
```

5. Open:

```text
http://127.0.0.1:8765
```

The dashboard is prebuilt and served by the Python control-plane process; Node/npm is not
required at runtime.
