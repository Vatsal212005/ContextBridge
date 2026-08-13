"""Live local observability verification for ContextBridge Milestone 4.

This script uses the in-memory MCP client, creates a harmless health call, then
reads the SQLite-backed metrics and recent-call history. It makes no GitHub
write request and requires no additional token permissions.
"""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from contextbridge.server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        health = await client.call_tool("health", {})
        if health.is_error:
            raise SystemExit("health tool failed")

        metrics = await client.call_tool("get_tool_metrics", {"all_time": True})
        recent = await client.call_tool("get_recent_tool_calls", {"limit": 5})

    print("Telemetry database is operational.")
    print(json.dumps(metrics.structured_content, indent=2))
    print("\nMost recent tool calls:")
    print(json.dumps(recent.structured_content, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
