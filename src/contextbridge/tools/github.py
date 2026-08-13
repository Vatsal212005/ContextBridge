"""Non-destructive GitHub connection tools for Milestone 2."""

from __future__ import annotations

from typing import Any

from contextbridge.config import settings
from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubError
from contextbridge.telemetry.instrumentation import observed_tool


@observed_tool(risk_level="read")
async def github_connection_status() -> dict[str, Any]:
    """Check GitHub authentication and return the connected account plus rate-limit state."""
    if not settings.github_token:
        return {
            "connected": False,
            "configured": False,
            "error": {
                "type": "not_configured",
                "message": "Set GITHUB_TOKEN in .env, then restart the MCP server.",
                "retryable": False,
            },
        }

    client = GitHubClient(
        token=settings.github_token,
        base_url=settings.github_api_url,
        api_version=settings.github_api_version,
        timeout_seconds=settings.github_timeout_seconds,
        max_retries=settings.github_max_retries,
    )
    try:
        user = await client.get_authenticated_user()
        rate_limit = await client.get_rate_limit()
        return {
            "connected": True,
            "configured": True,
            "user": user.as_dict(),
            "api_rate_limit": rate_limit.as_dict(),
            "api_version": settings.github_api_version,
        }
    except GitHubError as exc:
        return {
            "connected": False,
            "configured": True,
            "error": exc.as_dict(),
            "api_version": settings.github_api_version,
        }
    finally:
        await client.aclose()
