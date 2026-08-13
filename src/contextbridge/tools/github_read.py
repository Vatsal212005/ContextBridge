"""Read-only GitHub MCP tools for ContextBridge Milestone 3."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from contextbridge.config import settings
from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubError
from contextbridge.github.read_api import GitHubReadAPI
from contextbridge.telemetry.instrumentation import observed_tool

T = TypeVar("T")


def _client() -> GitHubClient:
    return GitHubClient(
        token=settings.github_token,
        base_url=settings.github_api_url,
        api_version=settings.github_api_version,
        timeout_seconds=settings.github_timeout_seconds,
        max_retries=settings.github_max_retries,
    )


async def _execute(operation: Callable[[GitHubReadAPI], Awaitable[T]]) -> dict[str, Any] | T:
    if not settings.github_token:
        return {
            "ok": False,
            "error": {
                "type": "not_configured",
                "message": "Set GITHUB_TOKEN in .env, then restart the MCP server.",
                "retryable": False,
            },
        }
    client = _client()
    try:
        result = await operation(GitHubReadAPI(client))
        if isinstance(result, dict):
            return {"ok": True, **result}
        return result
    except GitHubError as exc:
        return {"ok": False, "error": exc.as_dict()}
    except ValueError as exc:
        return {
            "ok": False,
            "error": {"type": "invalid_arguments", "message": str(exc), "retryable": False},
        }
    finally:
        await client.aclose()


@observed_tool(risk_level="read")
async def list_repositories(
    visibility: Literal["all", "public", "private"] = "all",
    sort: Literal["created", "updated", "pushed", "full_name"] = "updated",
    direction: Literal["asc", "desc"] = "desc",
    max_results: int = 50,
) -> dict[str, Any]:
    """List repositories accessible to the authenticated GitHub token. Read-only."""
    return await _execute(
        lambda api: api.list_repositories(
            visibility=visibility, sort=sort, direction=direction, max_results=max_results
        )
    )


@observed_tool(risk_level="read")
async def get_repository(owner: str, repo: str) -> dict[str, Any]:
    """Get metadata for one GitHub repository. Read-only."""
    return await _execute(lambda api: api.get_repository(owner=owner, repo=repo))


@observed_tool(risk_level="read")
async def search_issues(
    query: str = "",
    owner: str | None = None,
    repo: str | None = None,
    state: Literal["open", "closed", "all"] = "open",
    assignee: str | None = None,
    labels: list[str] | None = None,
    author: str | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """Search GitHub issues across accessible repositories using safe structured filters. Read-only."""
    return await _execute(
        lambda api: api.search_issues(
            query=query,
            owner=owner,
            repo=repo,
            state=state,
            assignee=assignee,
            labels=labels,
            author=author,
            max_results=max_results,
        )
    )


@observed_tool(risk_level="read")
async def get_issue(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
    """Get one GitHub issue by repository and number. Read-only."""
    return await _execute(
        lambda api: api.get_issue(owner=owner, repo=repo, issue_number=issue_number)
    )


@observed_tool(risk_level="read")
async def list_pull_requests(
    owner: str,
    repo: str,
    state: Literal["open", "closed", "all"] = "open",
    sort: Literal["created", "updated", "popularity", "long-running"] = "updated",
    direction: Literal["asc", "desc"] = "desc",
    base: str | None = None,
    head: str | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """List pull requests for a GitHub repository. Read-only."""
    return await _execute(
        lambda api: api.list_pull_requests(
            owner=owner,
            repo=repo,
            state=state,
            sort=sort,
            direction=direction,
            base=base,
            head=head,
            max_results=max_results,
        )
    )


@observed_tool(risk_level="read")
async def get_pull_request(owner: str, repo: str, pull_number: int) -> dict[str, Any]:
    """Get detailed metadata for one GitHub pull request. Read-only."""
    return await _execute(
        lambda api: api.get_pull_request(owner=owner, repo=repo, pull_number=pull_number)
    )


@observed_tool(risk_level="read")
async def list_commits(
    owner: str,
    repo: str,
    branch_or_sha: str | None = None,
    path: str | None = None,
    author: str | None = None,
    since: str | None = None,
    until: str | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """List commits in a repository, optionally filtered by branch, path, author, or time. Read-only."""
    return await _execute(
        lambda api: api.list_commits(
            owner=owner,
            repo=repo,
            branch_or_sha=branch_or_sha,
            path=path,
            author=author,
            since=since,
            until=until,
            max_results=max_results,
        )
    )


@observed_tool(risk_level="read")
async def get_file_contents(
    owner: str,
    repo: str,
    path: str,
    ref: str | None = None,
    max_chars: int = 100_000,
) -> dict[str, Any]:
    """Read a UTF-8 text file or list a directory in an accessible GitHub repository. Read-only."""
    return await _execute(
        lambda api: api.get_file_contents(
            owner=owner, repo=repo, path=path, ref=ref, max_chars=max_chars
        )
    )


@observed_tool(risk_level="read")
async def search_code(
    query: str,
    owner: str | None = None,
    repo: str | None = None,
    extension: str | None = None,
    language: str | None = None,
    path: str | None = None,
    max_results: int = 20,
) -> dict[str, Any]:
    """Search code visible to the authenticated GitHub token. Read-only; subject to GitHub code-search limits."""
    return await _execute(
        lambda api: api.search_code(
            query=query,
            owner=owner,
            repo=repo,
            extension=extension,
            language=language,
            path=path,
            max_results=max_results,
        )
    )


@observed_tool(risk_level="read")
async def get_workflow_runs(
    owner: str,
    repo: str,
    branch: str | None = None,
    event: str | None = None,
    status: str | None = None,
    actor: str | None = None,
    max_results: int = 25,
) -> dict[str, Any]:
    """List GitHub Actions workflow runs for a repository. Requires Actions: read. Read-only."""
    return await _execute(
        lambda api: api.get_workflow_runs(
            owner=owner,
            repo=repo,
            branch=branch,
            event=event,
            status=status,
            actor=actor,
            max_results=max_results,
        )
    )


@observed_tool(risk_level="read")
async def get_commit_status(owner: str, repo: str, ref: str) -> dict[str, Any]:
    """Get combined legacy commit-status contexts for a SHA, branch, or tag. Requires Commit statuses: read."""
    return await _execute(lambda api: api.get_commit_status(owner=owner, repo=repo, ref=ref))
