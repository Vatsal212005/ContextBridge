"""Async GitHub REST API client used by ContextBridge tools."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections.abc import AsyncIterator, Mapping
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from contextbridge.github.errors import (
    GitHubAuthenticationError,
    GitHubError,
    GitHubNotFoundError,
    GitHubPermissionError,
    GitHubRateLimitError,
    GitHubTransientError,
    GitHubValidationError,
)
from contextbridge.github.models import AuthenticatedUser, RateLimitSnapshot

logger = logging.getLogger(__name__)


class GitHubClient:
    """Minimal production-oriented async wrapper around the GitHub REST API."""

    def __init__(
        self,
        *,
        token: str | None,
        base_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        timeout_seconds: float = 20.0,
        max_retries: int = 3,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._api_version = api_version
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._request_lock = asyncio.Lock()
        self._last_rate_limit = RateLimitSnapshot()

    @property
    def configured(self) -> bool:
        return bool(self._token)

    @property
    def last_rate_limit(self) -> RateLimitSnapshot:
        return self._last_rate_limit

    async def __aenter__(self) -> "GitHubClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type: object, exc: object, tb: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
            "User-Agent": "ContextBridge-MCP",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                headers=self._headers(),
                timeout=httpx.Timeout(self._timeout_seconds),
                follow_redirects=False,
                transport=self._transport,
            )
        return self._client

    async def request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
    ) -> httpx.Response:
        """Send one GitHub request with serial execution and bounded retries."""
        client = await self._ensure_client()

        async with self._request_lock:
            last_error: GitHubError | None = None
            for attempt in range(self._max_retries + 1):
                try:
                    response = await client.request(
                        method,
                        path_or_url,
                        params=params,
                        json=json,
                    )
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                    last_error = GitHubTransientError(
                        kind="network_error",
                        message=f"GitHub request failed: {exc}",
                        retryable=True,
                    )
                    if attempt >= self._max_retries:
                        raise last_error from exc
                    await asyncio.sleep(self._backoff_seconds(attempt))
                    continue

                self._capture_rate_limit(response)

                if 200 <= response.status_code < 300:
                    return response

                error = self._normalize_error(response)
                last_error = error
                if not error.retryable or attempt >= self._max_retries:
                    raise error

                delay = error.retry_after_seconds
                if delay is not None and delay > 30.0:
                    # Do not block an MCP call for minutes/hours. Surface the
                    # retry metadata so the caller can try again later.
                    raise error
                if delay is None:
                    delay = self._backoff_seconds(attempt)
                await asyncio.sleep(max(0.0, delay))

            # Defensive; the loop always returns or raises.
            assert last_error is not None
            raise last_error

    async def get_authenticated_user(self) -> AuthenticatedUser:
        if not self.configured:
            raise GitHubAuthenticationError(
                kind="not_configured",
                message="GITHUB_TOKEN is not configured.",
                status_code=None,
                retryable=False,
            )
        response = await self.request("GET", "/user")
        data = response.json()
        return AuthenticatedUser(
            login=str(data["login"]),
            user_id=int(data["id"]),
            account_type=str(data.get("type", "User")),
            name=data.get("name"),
            html_url=data.get("html_url"),
        )

    async def get_rate_limit(self) -> RateLimitSnapshot:
        response = await self.request("GET", "/rate_limit")
        data = response.json()
        core = data.get("resources", {}).get("core", {})
        snapshot = RateLimitSnapshot(
            limit=_maybe_int(core.get("limit")),
            remaining=_maybe_int(core.get("remaining")),
            used=_maybe_int(core.get("used")),
            reset_epoch=_maybe_int(core.get("reset")),
            resource="core",
        )
        self._last_rate_limit = snapshot
        return snapshot

    async def iter_paginated(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        per_page: int = 100,
        max_pages: int | None = None,
    ) -> AsyncIterator[Any]:
        """Yield list items across GitHub Link-header pagination."""
        if per_page < 1 or per_page > 100:
            raise ValueError("per_page must be between 1 and 100")
        if max_pages is not None and max_pages < 1:
            raise ValueError("max_pages must be at least 1")

        request_params = dict(params or {})
        request_params["per_page"] = per_page
        next_url: str | None = path
        pages = 0

        while next_url is not None:
            response = await self.request(
                "GET",
                next_url,
                params=request_params if pages == 0 else None,
            )
            payload = response.json()
            if not isinstance(payload, list):
                raise GitHubValidationError(
                    kind="unexpected_response",
                    message="Expected a list from a paginated GitHub endpoint.",
                    status_code=response.status_code,
                    retryable=False,
                )

            for item in payload:
                yield item

            pages += 1
            if max_pages is not None and pages >= max_pages:
                break
            next_url = response.links.get("next", {}).get("url")

    def _capture_rate_limit(self, response: httpx.Response) -> None:
        headers = response.headers
        snapshot = RateLimitSnapshot(
            limit=_maybe_int(headers.get("x-ratelimit-limit")),
            remaining=_maybe_int(headers.get("x-ratelimit-remaining")),
            used=_maybe_int(headers.get("x-ratelimit-used")),
            reset_epoch=_maybe_int(headers.get("x-ratelimit-reset")),
            resource=headers.get("x-ratelimit-resource"),
        )
        if any(value is not None for value in (
            snapshot.limit,
            snapshot.remaining,
            snapshot.used,
            snapshot.reset_epoch,
            snapshot.resource,
        )):
            self._last_rate_limit = snapshot

    def _normalize_error(self, response: httpx.Response) -> GitHubError:
        data: dict[str, Any] = {}
        try:
            body = response.json()
            if isinstance(body, dict):
                data = body
        except ValueError:
            pass

        message = str(data.get("message") or f"GitHub API returned HTTP {response.status_code}")
        documentation_url = data.get("documentation_url")
        request_id = response.headers.get("x-github-request-id")
        status = response.status_code

        if status == 401:
            return GitHubAuthenticationError(
                kind="authentication_failed",
                message=message,
                status_code=status,
                retryable=False,
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        if status in {403, 429} and self._looks_rate_limited(response, message):
            return GitHubRateLimitError(
                kind="rate_limited",
                message=message,
                status_code=status,
                retryable=True,
                retry_after_seconds=self._retry_after_seconds(response),
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        if status == 403:
            return GitHubPermissionError(
                kind="permission_denied",
                message=message,
                status_code=status,
                retryable=False,
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        if status == 404:
            return GitHubNotFoundError(
                kind="not_found",
                message=message,
                status_code=status,
                retryable=False,
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        if status == 422:
            return GitHubValidationError(
                kind="validation_failed",
                message=message,
                status_code=status,
                retryable=False,
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        if status == 429 or 500 <= status <= 599:
            return GitHubTransientError(
                kind="transient_github_error",
                message=message,
                status_code=status,
                retryable=True,
                retry_after_seconds=self._retry_after_seconds(response),
                documentation_url=documentation_url,
                request_id=request_id,
                details=data,
            )

        return GitHubError(
            kind="github_api_error",
            message=message,
            status_code=status,
            retryable=False,
            documentation_url=documentation_url,
            request_id=request_id,
            details=data,
        )

    @staticmethod
    def _looks_rate_limited(response: httpx.Response, message: str) -> bool:
        if response.status_code == 429:
            return True
        if response.headers.get("x-ratelimit-remaining") == "0":
            return True
        lowered = message.lower()
        return "rate limit" in lowered or "secondary rate" in lowered

    @staticmethod
    def _retry_after_seconds(response: httpx.Response) -> float | None:
        retry_after = response.headers.get("retry-after")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                try:
                    retry_at = parsedate_to_datetime(retry_after).timestamp()
                    return max(0.0, retry_at - time.time())
                except (TypeError, ValueError, OverflowError):
                    pass

        remaining = response.headers.get("x-ratelimit-remaining")
        reset = response.headers.get("x-ratelimit-reset")
        if remaining == "0" and reset:
            try:
                return max(0.0, float(reset) - time.time())
            except ValueError:
                return None
        return None

    @staticmethod
    def _backoff_seconds(attempt: int) -> float:
        # Bounded exponential backoff plus jitter. Max is intentionally small here;
        # long rate-limit waits are represented to the caller instead of hanging.
        return min(8.0, (2**attempt) + random.uniform(0.0, 0.25))


def _maybe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
