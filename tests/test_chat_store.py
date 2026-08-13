from __future__ import annotations

import pytest

from contextbridge.telemetry.instrumentation import get_telemetry_store


@pytest.mark.asyncio
async def test_chat_session_persistence() -> None:
    store = get_telemetry_store()
    session = await store.create_chat_session(provider="openai", model="test-model")
    await store.add_chat_message(session_id=session["session_id"], role="user", content="Explain FeatureForge")
    await store.add_chat_message(session_id=session["session_id"], role="assistant", content="Test answer")
    messages = await store.list_chat_messages(session_id=session["session_id"])
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert (await store.get_chat_session(session["session_id"])) is not None


@pytest.mark.asyncio
async def test_chat_tool_calls_are_redacted_and_persisted() -> None:
    store = get_telemetry_store()
    session = await store.create_chat_session(provider="openai", model="test-model")
    await store.record_chat_tool_call(
        session_id=session["session_id"], turn_id="turn_1", call_id="call_chat_1",
        tool_name="get_repository", risk_level="read",
        arguments={"owner":"me","token":"secret"}, result={"ok":True}, status="success", duration_ms=12.5,
    )
    rows = await store.list_chat_tool_calls(session_id=session["session_id"])
    assert rows[0]["tool_name"] == "get_repository"
    assert rows[0]["arguments"]["token"] != "secret"
