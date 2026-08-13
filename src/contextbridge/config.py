"""Environment-backed application configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from contextbridge import __version__

# Load a project-local .env when present. MCP hosts do not always launch a
# stdio server with the project directory as cwd, so also resolve the root of
# this editable checkout. Existing process environment variables always win.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_env_candidates = [
    Path.cwd() / ".env",
    _PROJECT_ROOT / ".env",
]
for _env_path in dict.fromkeys(_env_candidates):
    if _env_path.is_file():
        load_dotenv(dotenv_path=_env_path, override=False)


def _int_env(name: str, default: int, *, minimum: int, maximum: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {value!r}") from exc
    if not (minimum <= parsed <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _float_env(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {value!r}") from exc
    if not (minimum <= parsed <= maximum):
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return parsed


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be a boolean (true/false), got {value!r}")


def _repo_allowlist_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    repos: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        parts = value.split("/")
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise ValueError(f"{name} entries must use owner/repo format; got {value!r}")
        repos.append(f"{parts[0].strip()}/{parts[1].strip()}")
    return tuple(dict.fromkeys(repos))


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime settings for ContextBridge."""

    name: str = "ContextBridge"
    version: str = __version__
    environment: str = "development"
    log_level: str = "INFO"
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000

    github_token: str | None = None
    github_api_url: str = "https://api.github.com"
    github_api_version: str = "2026-03-10"
    github_timeout_seconds: float = 20.0
    github_max_retries: int = 3

    # Mutation gates fail closed by default.
    dry_run: bool = True
    github_writes_enabled: bool = False
    github_write_repositories: tuple[str, ...] = ()

    # Milestone 6: every mutation request requires out-of-band human approval.
    confirmation_ttl_minutes: int = 30

    # Milestone 8: local control-plane dashboard. Non-loopback binding is
    # rejected unless a dashboard token is configured.
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    dashboard_token: str | None = None

    # Milestone 9: integrated dashboard chat. Credentials stay server-side.
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.6-flash"
    openai_api_key: str | None = None
    gemini_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com"
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_api_key: str | None = None
    llm_timeout_seconds: float = 120.0
    chat_max_tool_rounds: int = 8
    chat_history_messages: int = 30
    chat_read_only_default: bool = True

    database_path: Path = _PROJECT_ROOT / "data" / "contextbridge.db"

    @classmethod
    def from_env(cls) -> "Settings":
        transport = os.getenv("CONTEXTBRIDGE_TRANSPORT", "stdio").strip().lower()
        if transport not in {"stdio", "streamable-http"}:
            raise ValueError(
                "CONTEXTBRIDGE_TRANSPORT must be 'stdio' or 'streamable-http'"
            )

        token = os.getenv("GITHUB_TOKEN")
        token = token.strip() if token else None
        if token == "":
            token = None

        api_url = os.getenv("GITHUB_API_URL", "https://api.github.com").strip().rstrip("/")
        if not api_url.startswith(("https://", "http://")):
            raise ValueError("GITHUB_API_URL must start with http:// or https://")

        dashboard_token = os.getenv("CONTEXTBRIDGE_DASHBOARD_TOKEN")
        dashboard_token = dashboard_token.strip() if dashboard_token else None
        if dashboard_token == "":
            dashboard_token = None

        provider = os.getenv("CONTEXTBRIDGE_LLM_PROVIDER", "gemini").strip().lower() or "gemini"
        if provider not in {"openai", "gemini", "ollama"}:
            raise ValueError(
                "CONTEXTBRIDGE_LLM_PROVIDER must be 'openai', 'gemini', or 'ollama'"
            )
        openai_key = os.getenv("OPENAI_API_KEY")
        openai_key = openai_key.strip() if openai_key else None
        if openai_key == "":
            openai_key = None
        gemini_key = os.getenv("GEMINI_API_KEY")
        gemini_key = gemini_key.strip() if gemini_key else None
        if gemini_key == "":
            gemini_key = None
        ollama_key = os.getenv("OLLAMA_API_KEY")
        ollama_key = ollama_key.strip() if ollama_key else None
        if ollama_key == "":
            ollama_key = None

        db_raw = os.getenv("CONTEXTBRIDGE_DB_PATH", "data/contextbridge.db").strip()
        database_path = Path(db_raw).expanduser()
        if not database_path.is_absolute():
            database_path = (_PROJECT_ROOT / database_path).resolve()

        return cls(
            name=os.getenv("CONTEXTBRIDGE_NAME", "ContextBridge").strip() or "ContextBridge",
            environment=os.getenv("CONTEXTBRIDGE_ENV", "development").strip() or "development",
            log_level=os.getenv("CONTEXTBRIDGE_LOG_LEVEL", "INFO").strip().upper() or "INFO",
            transport=transport,
            host=os.getenv("CONTEXTBRIDGE_HOST", "127.0.0.1").strip() or "127.0.0.1",
            port=_int_env("CONTEXTBRIDGE_PORT", 8000, minimum=1, maximum=65535),
            github_token=token,
            github_api_url=api_url,
            github_api_version=(
                os.getenv("GITHUB_API_VERSION", "2026-03-10").strip() or "2026-03-10"
            ),
            github_timeout_seconds=_float_env(
                "GITHUB_TIMEOUT_SECONDS", 20.0, minimum=1.0, maximum=120.0
            ),
            github_max_retries=_int_env(
                "GITHUB_MAX_RETRIES", 3, minimum=0, maximum=8
            ),
            dry_run=_bool_env("CONTEXTBRIDGE_DRY_RUN", True),
            github_writes_enabled=_bool_env("GITHUB_WRITES_ENABLED", False),
            github_write_repositories=_repo_allowlist_env("GITHUB_WRITE_REPOSITORIES"),
            confirmation_ttl_minutes=_int_env(
                "CONTEXTBRIDGE_CONFIRMATION_TTL_MINUTES", 30, minimum=1, maximum=1440
            ),
            dashboard_host=(
                os.getenv("CONTEXTBRIDGE_DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
            ),
            dashboard_port=_int_env(
                "CONTEXTBRIDGE_DASHBOARD_PORT", 8765, minimum=1, maximum=65535
            ),
            dashboard_token=dashboard_token,
            llm_provider=provider,
            llm_model=(
                os.getenv("CONTEXTBRIDGE_LLM_MODEL", "gemini-3.6-flash").strip()
                or "gemini-3.6-flash"
            ),
            openai_api_key=openai_key,
            gemini_api_key=gemini_key,
            openai_base_url=(os.getenv("OPENAI_BASE_URL", "https://api.openai.com").strip().rstrip("/") or "https://api.openai.com"),
            ollama_base_url=(os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/") or "http://127.0.0.1:11434"),
            ollama_api_key=ollama_key,
            llm_timeout_seconds=_float_env("CONTEXTBRIDGE_LLM_TIMEOUT_SECONDS", 120.0, minimum=5.0, maximum=600.0),
            chat_max_tool_rounds=_int_env("CONTEXTBRIDGE_CHAT_MAX_TOOL_ROUNDS", 8, minimum=1, maximum=20),
            chat_history_messages=_int_env("CONTEXTBRIDGE_CHAT_HISTORY_MESSAGES", 30, minimum=2, maximum=200),
            chat_read_only_default=_bool_env("CONTEXTBRIDGE_CHAT_READ_ONLY_DEFAULT", True),
            database_path=database_path,
        )


settings = Settings.from_env()
