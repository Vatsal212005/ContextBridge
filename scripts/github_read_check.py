"""Live read-only GitHub verification for Milestone 3.

This script only lists repositories accessible to the configured token. It does
not create, edit, close, merge, label, or delete anything.
"""

from __future__ import annotations

import asyncio
import json

from contextbridge.config import settings
from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubError
from contextbridge.github.read_api import GitHubReadAPI


async def main() -> None:
    if not settings.github_token:
        raise SystemExit("GITHUB_TOKEN is missing from .env")

    client = GitHubClient(
        token=settings.github_token,
        base_url=settings.github_api_url,
        api_version=settings.github_api_version,
        timeout_seconds=settings.github_timeout_seconds,
        max_retries=settings.github_max_retries,
    )
    try:
        result = await GitHubReadAPI(client).list_repositories(max_results=10)
        print(json.dumps({"connected": True, **result}, indent=2))
    except GitHubError as exc:
        print(json.dumps({"connected": False, "error": exc.as_dict()}, indent=2))
        raise SystemExit(1) from exc
    finally:
        await client.aclose()


if __name__ == "__main__":
    asyncio.run(main())
