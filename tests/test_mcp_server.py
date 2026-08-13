from __future__ import annotations

import pytest
from mcp import Client

from contextbridge.server import mcp


M8_TOOLS = {
    "server_info",
    "health",
    "github_connection_status",
    "list_repositories",
    "get_repository",
    "search_issues",
    "get_issue",
    "list_pull_requests",
    "get_pull_request",
    "list_commits",
    "get_file_contents",
    "search_code",
    "get_workflow_runs",
    "get_commit_status",
    "get_tool_metrics",
    "get_recent_tool_calls",
    "get_audit_summary",
    "get_write_policy",
    "list_pending_actions",
    "get_pending_action",
    "execute_approved_action",
    "create_issue",
    "add_issue_comment",
    "add_labels",
    "close_issue",
    "reopen_issue",
    "get_evaluation_summary",
}

FORBIDDEN_TOOLS = {
    "delete_repository",
    "delete_file",
    "create_or_update_file",
    "push_commit",
    "delete_branch",
    "force_push",
    "merge_pull_request",
    "modify_repository_settings",
    "modify_workflow",
}


@pytest.mark.asyncio
async def test_tools_are_registered() -> None:
    async with Client(mcp) as client:
        result = await client.list_tools()
        names = {tool.name for tool in result.tools}

    assert M8_TOOLS.issubset(names)
    assert names.isdisjoint(FORBIDDEN_TOOLS)


@pytest.mark.asyncio
async def test_server_info_tool() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("server_info", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["name"] == "ContextBridge"
    assert result.structured_content["version"] == "0.9.1"
    assert result.structured_content["status"] == "healthy"


@pytest.mark.asyncio
async def test_health_tool() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool("health", {})

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == "healthy"


@pytest.mark.asyncio
async def test_create_issue_requires_human_confirmation_by_default() -> None:
    async with Client(mcp) as client:
        result = await client.call_tool(
            "create_issue",
            {
                "owner": "contextbridge-safety-test",
                "repo": "no-live-request",
                "title": "dry run",
                "body": "must not reach GitHub",
            },
        )

    assert result.is_error is False
    assert result.structured_content is not None
    assert result.structured_content["status"] == "confirmation_required"
    assert result.structured_content["github_request_sent"] is False
    assert result.structured_content["human_confirmation"]["mcp_approval_available"] is False
