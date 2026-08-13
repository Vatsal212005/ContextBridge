from __future__ import annotations

import pytest

from contextbridge.config import Settings


def test_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = [
        "CONTEXTBRIDGE_NAME", "CONTEXTBRIDGE_ENV", "CONTEXTBRIDGE_LOG_LEVEL",
        "CONTEXTBRIDGE_TRANSPORT", "CONTEXTBRIDGE_HOST", "CONTEXTBRIDGE_PORT",
        "GITHUB_TOKEN", "GITHUB_API_URL", "GITHUB_API_VERSION",
        "GITHUB_TIMEOUT_SECONDS", "GITHUB_MAX_RETRIES", "CONTEXTBRIDGE_DB_PATH",
        "CONTEXTBRIDGE_DRY_RUN", "GITHUB_WRITES_ENABLED", "GITHUB_WRITE_REPOSITORIES",
        "CONTEXTBRIDGE_DASHBOARD_HOST", "CONTEXTBRIDGE_DASHBOARD_PORT", "CONTEXTBRIDGE_DASHBOARD_TOKEN",
        "CONTEXTBRIDGE_LLM_PROVIDER", "CONTEXTBRIDGE_LLM_MODEL", "OPENAI_API_KEY",
        "GEMINI_API_KEY", "OLLAMA_API_KEY",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    value = Settings.from_env()
    assert value.name == "ContextBridge"
    assert value.transport == "stdio"
    assert value.port == 8000
    assert value.github_token is None
    assert value.github_api_version == "2026-03-10"
    assert value.dry_run is True
    assert value.github_writes_enabled is False
    assert value.github_write_repositories == ()
    assert value.database_path.name == "contextbridge.db"
    assert value.dashboard_host == "127.0.0.1"
    assert value.dashboard_port == 8765
    assert value.dashboard_token is None
    assert value.llm_provider == "gemini"
    assert value.llm_model == "gemini-3.6-flash"
    assert value.gemini_api_key is None


def test_custom_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_PORT", "9000")
    monkeypatch.setenv("GITHUB_TOKEN", "abc")
    monkeypatch.setenv("GITHUB_MAX_RETRIES", "5")
    value = Settings.from_env()
    assert value.port == 9000
    assert value.github_token == "abc"
    assert value.github_max_retries == 5


def test_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_PORT", "70000")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_invalid_api_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_API_URL", "api.github.com")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_custom_database_path_resolves(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    custom = tmp_path / "telemetry.sqlite3"
    monkeypatch.setenv("CONTEXTBRIDGE_DB_PATH", str(custom))
    value = Settings.from_env()
    assert value.database_path == custom


def test_write_safety_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_DRY_RUN", "false")
    monkeypatch.setenv("GITHUB_WRITES_ENABLED", "true")
    monkeypatch.setenv("GITHUB_WRITE_REPOSITORIES", "Vatsal212005/FeatureForge,owner/repo")
    value = Settings.from_env()
    assert value.dry_run is False
    assert value.github_writes_enabled is True
    assert value.github_write_repositories == ("Vatsal212005/FeatureForge", "owner/repo")


def test_invalid_boolean_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_DRY_RUN", "maybe")
    with pytest.raises(ValueError):
        Settings.from_env()


def test_gemini_provider_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_LLM_PROVIDER", "gemini")
    monkeypatch.setenv("CONTEXTBRIDGE_LLM_MODEL", "gemini-3.6-flash")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    value = Settings.from_env()
    assert value.llm_provider == "gemini"
    assert value.llm_model == "gemini-3.6-flash"
    assert value.gemini_api_key == "gemini-secret"


def test_invalid_llm_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTEXTBRIDGE_LLM_PROVIDER", "unsupported")
    with pytest.raises(ValueError):
        Settings.from_env()
