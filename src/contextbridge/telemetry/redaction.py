"""Redaction helpers for telemetry-safe argument storage."""

from __future__ import annotations

from typing import Any

_SENSITIVE_TOKENS = {
    "token",
    "authorization",
    "password",
    "passwd",
    "secret",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
    "cookie",
}


def _is_sensitive_key(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return any(token in normalized for token in _SENSITIVE_TOKENS)


def redact(value: Any, *, max_string_chars: int = 2_000) -> Any:
    """Recursively redact likely credentials and bound very large telemetry values."""
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            result[key_text] = "[REDACTED]" if _is_sensitive_key(key_text) else redact(
                item, max_string_chars=max_string_chars
            )
        return result
    if isinstance(value, (list, tuple, set)):
        return [redact(item, max_string_chars=max_string_chars) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str):
        if len(value) > max_string_chars:
            return value[:max_string_chars] + f"… <truncated {len(value) - max_string_chars} chars>"
        return value
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return str(value)
