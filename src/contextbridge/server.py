"""ContextBridge MCP server entrypoint."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Literal, cast

from mcp.server import MCPServer

from contextbridge.config import settings
from contextbridge.logging_config import configure_logging
from contextbridge.tools.github import github_connection_status
from contextbridge.tools.github_read import (
    get_commit_status,
    get_file_contents,
    get_issue,
    get_pull_request,
    get_repository,
    get_workflow_runs,
    list_commits,
    list_pull_requests,
    list_repositories,
    search_code,
    search_issues,
)
from contextbridge.tools.system import health, server_info
from contextbridge.tools.github_write import (
    add_issue_comment,
    add_labels,
    close_issue,
    create_issue,
    execute_approved_action,
    get_pending_action,
    get_write_policy,
    list_pending_actions,
    reopen_issue,
)
from contextbridge.tools.telemetry import get_audit_summary, get_recent_tool_calls, get_tool_metrics
from contextbridge.tools.evaluation import get_evaluation_summary
from contextbridge.telemetry.instrumentation import get_telemetry_store

configure_logging(settings.log_level)
logger = logging.getLogger(__name__)

mcp = MCPServer(
    settings.name,
    version=settings.version,
    instructions=(
        "ContextBridge securely exposes authenticated developer-system tools to AI clients. "
        "Signed one-time pending actions require out-of-band human confirmation; approval/rejection is "
        "intentionally absent from the MCP surface and is available only through the local CLI/dashboard. "
        "DRY_RUN remains enabled by default, so approved actions are simulated without contacting GitHub. "
        "Milestones 7+8 add provider-agnostic tool-selection evaluation and a local React control plane. "
        "Repository/code/admin mutation capabilities remain unimplemented."
    ),
)

# System and connection tools.
mcp.tool()(server_info)
mcp.tool()(health)
mcp.tool()(github_connection_status)

# Milestone 3: GitHub read-only surface.
mcp.tool()(list_repositories)
mcp.tool()(get_repository)
mcp.tool()(search_issues)
mcp.tool()(get_issue)
mcp.tool()(list_pull_requests)
mcp.tool()(get_pull_request)
mcp.tool()(list_commits)
mcp.tool()(get_file_contents)
mcp.tool()(search_code)
mcp.tool()(get_workflow_runs)
mcp.tool()(get_commit_status)

# Milestone 4: local read-only telemetry/observability surface.
mcp.tool()(get_tool_metrics)
mcp.tool()(get_recent_tool_calls)
mcp.tool()(get_audit_summary)
mcp.tool()(get_evaluation_summary)

# Milestone 6: signed pending actions + out-of-band human confirmation.
mcp.tool()(get_write_policy)
mcp.tool()(list_pending_actions)
mcp.tool()(get_pending_action)
mcp.tool()(execute_approved_action)
mcp.tool()(create_issue)
mcp.tool()(add_issue_comment)
mcp.tool()(add_labels)
mcp.tool()(close_issue)
mcp.tool()(reopen_issue)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ContextBridge MCP server")
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=settings.transport,
        help="MCP transport to use (default: environment setting or stdio)",
    )
    parser.add_argument("--host", default=settings.host, help="HTTP bind host")
    parser.add_argument("--port", type=int, default=settings.port, help="HTTP bind port")
    return parser


def main() -> None:
    """Run ContextBridge using stdio by default or Streamable HTTP when requested."""
    args = _build_parser().parse_args()
    transport = cast(Literal["stdio", "streamable-http"], args.transport)

    logger.info(
        "Starting %s v%s using %s transport",
        settings.name,
        settings.version,
        transport,
    )
    asyncio.run(
        get_telemetry_store().record_system_event(
            kind="server_start",
            status="ok",
            message=f"{settings.name} v{settings.version} started.",
            metadata={"transport": transport, "environment": settings.environment},
        )
    )

    if transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport="streamable-http", host=args.host, port=args.port)


if __name__ == "__main__":
    main()
