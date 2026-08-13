from __future__ import annotations

import json

import httpx
import pytest

from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import (
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubValidationError,
)


def response(status: int, payload: object, *, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(
        status,
        content=json.dumps(payload).encode(),
        headers={"content-type": "application/json", **(headers or {})},
    )


@pytest.mark.asyncio
async def test_authenticated_user_and_rate_limit_headers() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer secret"
        assert request.headers["x-github-api-version"] == "2026-03-10"
        return response(
            200,
            {"login": "octocat", "id": 1, "type": "User", "name": "Mona", "html_url": "https://github.com/octocat"},
            headers={
                "x-ratelimit-limit": "5000",
                "x-ratelimit-remaining": "4999",
                "x-ratelimit-used": "1",
                "x-ratelimit-reset": "2000000000",
                "x-ratelimit-resource": "core",
            },
        )

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        user = await client.get_authenticated_user()
        assert user.login == "octocat"
        assert client.last_rate_limit.remaining == 4999
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unconfigured_token_fails_before_network() -> None:
    client = GitHubClient(token=None)
    with pytest.raises(GitHubAuthenticationError) as exc:
        await client.get_authenticated_user()
    assert exc.value.kind == "not_configured"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, GitHubAuthenticationError),
        (403, GitHubPermissionError),
        (404, GitHubNotFoundError),
        (422, GitHubValidationError),
    ],
)
async def test_normalized_non_retryable_errors(status: int, expected: type[Exception]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return response(status, {"message": "boom"})

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        with pytest.raises(expected):
            await client.request("GET", "/x")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_primary_rate_limit_is_normalized() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return response(
            403,
            {"message": "API rate limit exceeded"},
            headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "2000000000"},
        )

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        with pytest.raises(GitHubRateLimitError) as exc:
            await client.request("GET", "/x")
        assert exc.value.retryable is True
        assert exc.value.retry_after_seconds is not None
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_link_header_pagination() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            assert request.url.params["per_page"] == "2"
            return response(
                200,
                [{"id": 1}, {"id": 2}],
                headers={"link": '<https://api.github.com/items?page=2&per_page=2>; rel="next"'},
            )
        return response(200, [{"id": 3}])

    client = GitHubClient(token="secret", transport=httpx.MockTransport(handler), max_retries=0)
    try:
        items = [item async for item in client.iter_paginated("/items", per_page=2)]
    finally:
        await client.aclose()

    assert [item["id"] for item in items] == [1, 2, 3]
    assert calls == 2
