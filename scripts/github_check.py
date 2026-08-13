"""Manual GitHub connectivity check using the configured .env token."""

from __future__ import annotations

import asyncio
import json

from contextbridge.tools.github import github_connection_status


async def main() -> None:
    result = await github_connection_status()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
