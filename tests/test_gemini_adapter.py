from google.genai import types

from contextbridge.chat import _gemini_tool


def test_gemini_tool_schema_adapter() -> None:
    declaration = _gemini_tool(
        {
            "name": "get_repository",
            "description": "Read repository metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "owner": {"type": "string"},
                    "repo": {"type": "string"},
                },
                "required": ["owner", "repo"],
            },
        },
        types,
    )
    assert declaration.name == "get_repository"
    assert declaration.parameters_json_schema["required"] == ["owner", "repo"]

def test_gemini_function_response_helper_accepts_contextbridge_payload() -> None:
    # Regression: google-genai Part.from_function_response accepts name + response;
    # passing id= caused every real MCP tool round to fail before Gemini could continue.
    part = types.Part.from_function_response(
        name="get_repository",
        response={"result": {"ok": True, "name": "FeatureForge"}},
    )
    assert part.function_response is not None
    assert part.function_response.name == "get_repository"
    assert part.function_response.response["result"]["ok"] is True

