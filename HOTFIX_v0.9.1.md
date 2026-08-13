# ContextBridge v0.9.1 Gemini hotfix

This hotfix corrects the manual Gemini function-response bridge.

The previous build passed an `id` keyword to `types.Part.from_function_response()`. In google-genai 2.x, the helper accepts `name` and `response`; the ContextBridge call ID is retained internally for telemetry and is not sent through that helper.

The patch also updates three stale tests that still expected v0.9.0 / schema v3.

No GitHub write settings, tokens, SQLite data, or signing material are included or changed.
