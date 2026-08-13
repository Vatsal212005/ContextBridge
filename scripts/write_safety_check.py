"""Milestone 6A safety check: mutation requests must queue without touching GitHub."""
from __future__ import annotations

import asyncio
import json

from contextbridge.config import settings
import contextbridge.tools.github_write as write_tools


def explode_client():
    raise AssertionError("GitHub client was constructed during a confirmation request")


async def main() -> None:
    if settings.dry_run is not True or settings.github_writes_enabled is not False:
        raise SystemExit(
            "REFUSED: Milestone 6A verification requires CONTEXTBRIDGE_DRY_RUN=true "
            "and GITHUB_WRITES_ENABLED=false."
        )

    original_client = write_tools._client
    write_tools._client = explode_client
    try:
        result = await write_tools.create_issue(
            "contextbridge-safety-test",
            "no-live-request",
            "M6 confirmation safety verification",
            "This is only a signed pending-action preview and must never be sent to GitHub.",
        )
    finally:
        write_tools._client = original_client

    print("Current write policy:")
    print(json.dumps(await write_tools.get_write_policy(), indent=2))
    print("\nPending mutation request:")
    print(json.dumps(result, indent=2))

    assert result["status"] == "confirmation_required"
    assert result["github_request_sent"] is False
    assert result["action"]["status"] == "pending"
    assert result["human_confirmation"]["mcp_approval_available"] is False
    print("\nPASS: mutation was queued for out-of-band human confirmation; no GitHub client was constructed.")


if __name__ == "__main__":
    asyncio.run(main())
