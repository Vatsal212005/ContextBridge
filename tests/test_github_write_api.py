from __future__ import annotations

import httpx
import pytest

from contextbridge.github.client import GitHubClient
from contextbridge.github.write_api import GitHubWriteAPI


@pytest.mark.asyncio
async def test_create_issue_uses_only_issues_endpoint() -> None:
    seen: list[tuple[str, str, dict]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, __import__("json").loads(request.content)))
        return httpx.Response(
            201,
            json={"number": 3, "title": "x", "state": "open", "html_url": "https://example/3"},
        )

    client = GitHubClient(token="x", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubWriteAPI(client).create_issue(
            owner="owner", repo="repo", title="x", body="body"
        )
    finally:
        await client.aclose()

    assert result["action"] == "created"
    assert seen == [("POST", "/repos/owner/repo/issues", {"title": "x", "body": "body"})]


@pytest.mark.asyncio
async def test_issue_mutation_rejects_pull_request_numbers_before_patch() -> None:
    seen: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(
            200,
            json={"number": 5, "pull_request": {"url": "https://api.github.com/pr/5"}},
        )

    client = GitHubClient(token="x", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        with pytest.raises(ValueError, match="issue-only"):
            await GitHubWriteAPI(client).close_issue(owner="owner", repo="repo", issue_number=5)
    finally:
        await client.aclose()

    assert seen == [("GET", "/repos/owner/repo/issues/5")]
