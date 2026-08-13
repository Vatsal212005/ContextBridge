from __future__ import annotations

import base64
import json

import httpx
import pytest

from contextbridge.github.client import GitHubClient
from contextbridge.github.read_api import GitHubReadAPI


def response(status: int, payload: object, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


@pytest.mark.asyncio
async def test_list_repositories_is_bounded_and_compact() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/user/repos"
        assert request.url.params["visibility"] == "all"
        assert request.url.params["per_page"] == "2"
        return response(
            200,
            [
                {"name": "one", "full_name": "me/one", "private": True, "html_url": "https://github.com/me/one"},
                {"name": "two", "full_name": "me/two", "private": False, "html_url": "https://github.com/me/two"},
            ],
        )

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).list_repositories(max_results=2)
    finally:
        await client.aclose()
    assert result["count"] == 2
    assert result["repositories"][0]["full_name"] == "me/one"


@pytest.mark.asyncio
async def test_search_issues_adds_issue_and_filters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        q = request.url.params["q"]
        assert "crash" in q
        assert "is:issue" in q
        assert "is:open" in q
        assert "repo:me/app" in q
        assert "assignee:@me" in q
        assert 'label:"bug"' in q
        return response(200, {"total_count": 1, "items": [{"number": 7, "title": "Crash", "state": "open"}]})

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).search_issues(
            query="crash", owner="me", repo="app", assignee="@me", labels=["bug"]
        )
    finally:
        await client.aclose()
    assert result["total_count"] == 1
    assert result["issues"][0]["number"] == 7


@pytest.mark.asyncio
async def test_get_file_contents_decodes_utf8_and_truncates() -> None:
    encoded = base64.b64encode(b"hello world").decode()

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/me/app/contents/src/main.py"
        assert request.url.params["ref"] == "main"
        return response(
            200,
            {"type": "file", "name": "main.py", "path": "src/main.py", "sha": "abc", "size": 11, "encoding": "base64", "content": encoded},
        )

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).get_file_contents(
            owner="me", repo="app", path="src/main.py", ref="main", max_chars=5
        )
    finally:
        await client.aclose()
    assert result["binary"] is False
    assert result["truncated"] is True
    assert result["content"].startswith("hello")


@pytest.mark.asyncio
async def test_workflow_runs_parses_object_pagination() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/me/app/actions/runs"
        assert request.url.params["status"] == "failure"
        return response(
            200,
            {"total_count": 1, "workflow_runs": [{"id": 99, "name": "CI", "status": "completed", "conclusion": "failure"}]},
        )

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).get_workflow_runs(
            owner="me", repo="app", status="failure", max_results=10
        )
    finally:
        await client.aclose()
    assert result["total_count"] == 1
    assert result["workflow_runs"][0]["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_commit_status_encodes_branch_ref() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/me/app/commits/feature/thing/status"
        return response(200, {"state": "success", "sha": "abc", "total_count": 1, "statuses": [{"state": "success", "context": "ci"}]})

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).get_commit_status(
            owner="me", repo="app", ref="feature/thing"
        )
    finally:
        await client.aclose()
    assert result["state"] == "success"
    assert result["statuses"][0]["context"] == "ci"


@pytest.mark.asyncio
async def test_search_code_builds_repository_qualifier() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/search/code"
        q = request.url.params["q"]
        assert "validate_feature" in q
        assert "repo:me/app" in q
        assert "extension:py" in q
        return response(200, {"total_count": 1, "items": [{"name": "features.py", "path": "src/features.py", "sha": "abc", "repository": {"full_name": "me/app"}}]})

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        result = await GitHubReadAPI(client).search_code(
            query="validate_feature", owner="me", repo="app", extension="py"
        )
    finally:
        await client.aclose()
    assert result["count"] == 1
    assert result["matches"][0]["path"] == "src/features.py"
