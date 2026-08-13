from __future__ import annotations

import asyncio
import json

from contextbridge.chat import provider_status
from contextbridge.telemetry.instrumentation import get_telemetry_store


async def main() -> None:
    store = get_telemetry_store()
    session = await store.create_chat_session(provider="verification", model="no-network", title="M9 chat persistence check")
    await store.add_chat_message(session_id=session["session_id"], role="user", content="What does FeatureForge do?")
    await store.record_chat_tool_call(
        session_id=session["session_id"], turn_id="turn_check", call_id=f"check_{session['session_id']}",
        tool_name="get_repository", risk_level="read", arguments={"owner":"Vatsal212005","repo":"FeatureForge"},
        result={"ok":True,"verification":True}, status="success", duration_ms=0.1,
    )
    detail={
        "provider": provider_status(),
        "session": await store.get_chat_session(session["session_id"]),
        "messages": await store.list_chat_messages(session_id=session["session_id"]),
        "tool_calls": await store.list_chat_tool_calls(session_id=session["session_id"]),
    }
    print("Integrated chat persistence is operational.")
    print(json.dumps(detail, indent=2, ensure_ascii=False, default=str))
    assert detail["provider"]["credentials_exposed_to_browser"] is False
    assert len(detail["messages"]) == 1
    assert len(detail["tool_calls"]) == 1
    print("PASS: chat sessions/messages/tool timeline persist locally without making a model or GitHub request.")


if __name__ == "__main__":
    asyncio.run(main())
