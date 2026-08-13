"""Offline verification for the v0.9.1 Gemini adapter. No API request is made."""
from __future__ import annotations

from google import genai  # noqa: F401
from google.genai import types

from contextbridge import __version__
from contextbridge.chat import _gemini_tool, provider_status


def main() -> None:
    tool = {
        "name": "example_read_tool",
        "description": "Offline Gemini function-declaration verification.",
        "inputSchema": {
            "type": "object",
            "properties": {"owner": {"type": "string"}},
            "required": ["owner"],
        },
    }
    declaration = _gemini_tool(tool, types)
    status = provider_status()
    assert declaration.name == "example_read_tool"
    assert status["provider"] == "gemini"
    assert status["model"] == "gemini-3.6-flash"
    assert status["credentials_exposed_to_browser"] is False
    assert status["gemini_manual_function_calling"] is True
    print(f"ContextBridge v{__version__} Gemini adapter is operational.")
    print("Provider: gemini")
    print("Model: gemini-3.6-flash")
    print("Manual MCP function orchestration: enabled")
    print("API request made: no")
    print("PASS: Gemini SDK/schema integration loaded without exposing credentials or calling the model API.")


if __name__ == "__main__":
    main()
