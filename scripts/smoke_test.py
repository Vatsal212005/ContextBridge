"""In-memory MCP smoke test for ContextBridge."""

from __future__ import annotations

import asyncio
import json

from mcp import Client

from contextbridge.server import mcp


async def main() -> None:
    async with Client(mcp) as client:
        listed = await client.list_tools()
        names = sorted(tool.name for tool in listed.tools)
        print("Connected to ContextBridge")
        print("Tools:", ", ".join(names))

        info = await client.call_tool("server_info", {})
        print(json.dumps(info.structured_content, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
