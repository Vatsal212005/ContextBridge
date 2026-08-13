"""Read-only GitHub service operations used by MCP tools.

This module intentionally returns compact, stable dictionaries rather than raw
GitHub payloads. That reduces context size and keeps the MCP surface decoupled
from incidental REST response fields.
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Any, Literal
from urllib.parse import quote

from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubValidationError

_REPO_PART = re.compile(r"^[A-Za-z0-9_.-]+$")


def _repo_part(value: str, field: str) -> str:
    value = value.strip()
    if not value or not _REPO_PART.fullmatch(value):
        raise ValueError(f"{field} contains unsupported characters")
    return value


def _repo_path(owner: str, repo: str) -> str:
    owner = _repo_part(owner, "owner")
    repo = _repo_part(repo, "repo")
    return f"/repos/{owner}/{repo}"


def _bounded(value: int, *, minimum: int = 1, maximum: int = 100, name: str = "max_results") -> int:
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _user(login: Any) -> str | None:
    return login.get("login") if isinstance(login, dict) else None


def _labels(labels: Any) -> list[str]:
    if not isinstance(labels, list):
        return []
    out: list[str] = []
    for item in labels:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("name"):
            out.append(str(item["name"]))
    return out


def _excerpt(value: Any, limit: int = 4000) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + "\n…[truncated]"


class GitHubReadAPI:
    """High-level read-only GitHub operations."""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    async def list_repositories(
        self,
        *,
        visibility: Literal["all", "public", "private"] = "all",
        affiliation: str = "owner,collaborator,organization_member",
        sort: Literal["created", "updated", "pushed", "full_name"] = "updated",
        direction: Literal["asc", "desc"] = "desc",
        max_results: int = 50,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        params = {
            "visibility": visibility,
            "affiliation": affiliation,
            "sort": sort,
            "direction": direction,
        }
        items = await self._collect_list("/user/repos", params=params, max_results=max_results)
        return {
            "count": len(items),
            "repositories": [self._repository_summary(item) for item in items],
        }

    async def get_repository(self, *, owner: str, repo: str) -> dict[str, Any]:
        response = await self.client.request("GET", _repo_path(owner, repo))
        data = response.json()
        return {"repository": self._repository_detail(data)}

    async def search_issues(
        self,
        *,
        query: str = "",
        owner: str | None = None,
        repo: str | None = None,
        state: Literal["open", "closed", "all"] = "open",
        assignee: str | None = None,
        labels: list[str] | None = None,
        author: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        qualifiers: list[str] = ["is:issue"]
        if state != "all":
            qualifiers.append(f"is:{state}")
        if repo is not None:
            if owner is None:
                raise ValueError("owner is required when repo is provided")
            qualifiers.append(f"repo:{_repo_part(owner, 'owner')}/{_repo_part(repo, 'repo')}")
        elif owner is not None:
            qualifiers.append(f"user:{_repo_part(owner, 'owner')}")
        if assignee:
            qualifiers.append(f"assignee:{assignee.strip()}")
        if author:
            qualifiers.append(f"author:{author.strip()}")
        for label in labels or []:
            cleaned = label.strip().replace('"', "")
            if cleaned:
                qualifiers.append(f'label:"{cleaned}"')

        q = " ".join(part for part in [query.strip(), *qualifiers] if part)
        data = await self._search("/search/issues", q=q, max_results=max_results)
        return {
            "query": q,
            "total_count": data["total_count"],
            "count": len(data["items"]),
            "issues": [self._issue_summary(item) for item in data["items"]],
        }

    async def get_issue(self, *, owner: str, repo: str, issue_number: int) -> dict[str, Any]:
        if issue_number < 1:
            raise ValueError("issue_number must be positive")
        response = await self.client.request(
            "GET", f"{_repo_path(owner, repo)}/issues/{issue_number}"
        )
        data = response.json()
        if "pull_request" in data:
            return {
                "warning": "GitHub issue endpoints also represent pull requests; this number is a pull request.",
                "issue": self._issue_detail(data),
            }
        return {"issue": self._issue_detail(data)}

    async def list_pull_requests(
        self,
        *,
        owner: str,
        repo: str,
        state: Literal["open", "closed", "all"] = "open",
        sort: Literal["created", "updated", "popularity", "long-running"] = "updated",
        direction: Literal["asc", "desc"] = "desc",
        base: str | None = None,
        head: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        params: dict[str, Any] = {"state": state, "sort": sort, "direction": direction}
        if base:
            params["base"] = base
        if head:
            params["head"] = head
        items = await self._collect_list(
            f"{_repo_path(owner, repo)}/pulls", params=params, max_results=max_results
        )
        return {
            "count": len(items),
            "pull_requests": [self._pull_summary(item) for item in items],
        }

    async def get_pull_request(self, *, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        if pull_number < 1:
            raise ValueError("pull_number must be positive")
        response = await self.client.request(
            "GET", f"{_repo_path(owner, repo)}/pulls/{pull_number}"
        )
        return {"pull_request": self._pull_detail(response.json())}

    async def list_commits(
        self,
        *,
        owner: str,
        repo: str,
        branch_or_sha: str | None = None,
        path: str | None = None,
        author: str | None = None,
        since: str | None = None,
        until: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        params: dict[str, Any] = {}
        if branch_or_sha:
            params["sha"] = branch_or_sha
        if path:
            params["path"] = path
        if author:
            params["author"] = author
        if since:
            params["since"] = since
        if until:
            params["until"] = until

        items = await self._collect_list(
            f"{_repo_path(owner, repo)}/commits", params=params, max_results=max_results
        )
        return {"count": len(items), "commits": [self._commit_summary(item) for item in items]}

    async def get_file_contents(
        self,
        *,
        owner: str,
        repo: str,
        path: str,
        ref: str | None = None,
        max_chars: int = 100_000,
    ) -> dict[str, Any]:
        if max_chars < 1 or max_chars > 500_000:
            raise ValueError("max_chars must be between 1 and 500000")
        clean_path = path.strip("/")
        if not clean_path:
            raise ValueError("path is required")
        encoded_path = quote(clean_path, safe="/")
        params = {"ref": ref} if ref else None
        response = await self.client.request(
            "GET", f"{_repo_path(owner, repo)}/contents/{encoded_path}", params=params
        )
        data = response.json()

        if isinstance(data, list):
            return {
                "type": "directory",
                "path": clean_path,
                "entries": [self._content_entry(item) for item in data],
                "count": len(data),
            }
        if not isinstance(data, dict):
            raise GitHubValidationError(
                kind="unexpected_response",
                message="GitHub returned an unexpected repository-content payload.",
                status_code=response.status_code,
                retryable=False,
            )

        result: dict[str, Any] = {
            "type": data.get("type"),
            "name": data.get("name"),
            "path": data.get("path"),
            "sha": data.get("sha"),
            "size": data.get("size"),
            "html_url": data.get("html_url"),
        }

        if data.get("type") != "file":
            result["metadata"] = self._content_entry(data)
            return result

        content = data.get("content")
        encoding = data.get("encoding")
        if isinstance(content, str) and encoding == "base64":
            try:
                decoded = base64.b64decode(content, validate=False)
            except (binascii.Error, ValueError):
                result["content_available"] = False
                result["reason"] = "GitHub returned invalid base64 content."
                return result
            try:
                text = decoded.decode("utf-8")
            except UnicodeDecodeError:
                result["content_available"] = False
                result["binary"] = True
                result["reason"] = "File is not UTF-8 text; binary content is not returned to the model."
                return result
            result["binary"] = False
            result["truncated"] = len(text) > max_chars
            result["content"] = text[:max_chars]
            if result["truncated"]:
                result["content"] += "\n…[truncated by ContextBridge]"
            return result

        result["content_available"] = False
        result["reason"] = (
            "Inline content was not provided by the GitHub Contents API for this file. "
            "Use a smaller text file or a GitHub App/raw-content flow in a later milestone."
        )
        return result

    async def search_code(
        self,
        *,
        query: str,
        owner: str | None = None,
        repo: str | None = None,
        extension: str | None = None,
        language: str | None = None,
        path: str | None = None,
        max_results: int = 20,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        if not query.strip():
            raise ValueError("query is required")
        qualifiers: list[str] = []
        if repo is not None:
            if owner is None:
                raise ValueError("owner is required when repo is provided")
            qualifiers.append(f"repo:{_repo_part(owner, 'owner')}/{_repo_part(repo, 'repo')}")
        elif owner is not None:
            qualifiers.append(f"user:{_repo_part(owner, 'owner')}")
        if extension:
            qualifiers.append(f"extension:{extension.strip().lstrip('.')}")
        if language:
            qualifiers.append(f'language:"{language.strip().replace(chr(34), "")}"')
        if path:
            qualifiers.append(f'path:"{path.strip().replace(chr(34), "")}"')
        q = " ".join([query.strip(), *qualifiers])
        data = await self._search("/search/code", q=q, max_results=max_results)
        return {
            "query": q,
            "total_count": data["total_count"],
            "count": len(data["items"]),
            "matches": [self._code_summary(item) for item in data["items"]],
        }

    async def get_workflow_runs(
        self,
        *,
        owner: str,
        repo: str,
        branch: str | None = None,
        event: str | None = None,
        status: str | None = None,
        actor: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        max_results = _bounded(max_results)
        params: dict[str, Any] = {}
        if branch:
            params["branch"] = branch
        if event:
            params["event"] = event
        if status:
            params["status"] = status
        if actor:
            params["actor"] = actor
        payload = await self._collect_object_items(
            f"{_repo_path(owner, repo)}/actions/runs",
            key="workflow_runs",
            params=params,
            max_results=max_results,
        )
        return {
            "total_count": payload["total_count"],
            "count": len(payload["items"]),
            "workflow_runs": [self._workflow_run_summary(item) for item in payload["items"]],
        }

    async def get_commit_status(self, *, owner: str, repo: str, ref: str) -> dict[str, Any]:
        if not ref.strip():
            raise ValueError("ref is required")
        encoded_ref = quote(ref.strip(), safe="")
        response = await self.client.request(
            "GET", f"{_repo_path(owner, repo)}/commits/{encoded_ref}/status"
        )
        data = response.json()
        statuses = data.get("statuses", []) if isinstance(data, dict) else []
        return {
            "state": data.get("state") if isinstance(data, dict) else None,
            "sha": data.get("sha") if isinstance(data, dict) else None,
            "total_count": data.get("total_count") if isinstance(data, dict) else None,
            "statuses": [self._status_summary(item) for item in statuses if isinstance(item, dict)],
        }

    async def _collect_list(
        self,
        path: str,
        *,
        params: dict[str, Any] | None,
        max_results: int,
    ) -> list[dict[str, Any]]:
        collected: list[dict[str, Any]] = []
        async for item in self.client.iter_paginated(path, params=params, per_page=min(100, max_results)):
            if isinstance(item, dict):
                collected.append(item)
            if len(collected) >= max_results:
                break
        return collected

    async def _search(self, path: str, *, q: str, max_results: int) -> dict[str, Any]:
        response = await self.client.request(
            "GET", path, params={"q": q, "per_page": min(100, max_results), "page": 1}
        )
        data = response.json()
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise GitHubValidationError(
                kind="unexpected_response",
                message="GitHub returned an unexpected search payload.",
                status_code=response.status_code,
                retryable=False,
            )
        items = [item for item in data["items"][:max_results] if isinstance(item, dict)]
        return {"total_count": int(data.get("total_count", len(items))), "items": items}

    async def _collect_object_items(
        self,
        path: str,
        *,
        key: str,
        params: dict[str, Any] | None,
        max_results: int,
    ) -> dict[str, Any]:
        collected: list[dict[str, Any]] = []
        page = 1
        total_count: int | None = None
        while len(collected) < max_results:
            request_params = dict(params or {})
            request_params.update({"per_page": min(100, max_results - len(collected)), "page": page})
            response = await self.client.request("GET", path, params=request_params)
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get(key), list):
                raise GitHubValidationError(
                    kind="unexpected_response",
                    message=f"Expected '{key}' list in GitHub response.",
                    status_code=response.status_code,
                    retryable=False,
                )
            if total_count is None:
                total_count = int(data.get("total_count", 0))
            batch = [item for item in data[key] if isinstance(item, dict)]
            collected.extend(batch[: max_results - len(collected)])
            if not response.links.get("next") or not batch:
                break
            page += 1
        return {"total_count": total_count if total_count is not None else len(collected), "items": collected}

    @staticmethod
    def _repository_summary(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": data.get("name"),
            "full_name": data.get("full_name"),
            "private": data.get("private"),
            "description": data.get("description"),
            "default_branch": data.get("default_branch"),
            "language": data.get("language"),
            "archived": data.get("archived"),
            "fork": data.get("fork"),
            "updated_at": data.get("updated_at"),
            "pushed_at": data.get("pushed_at"),
            "html_url": data.get("html_url"),
        }

    @classmethod
    def _repository_detail(cls, data: dict[str, Any]) -> dict[str, Any]:
        result = cls._repository_summary(data)
        result.update(
            {
                "id": data.get("id"),
                "owner": _user(data.get("owner")),
                "visibility": data.get("visibility"),
                "size_kb": data.get("size"),
                "stars": data.get("stargazers_count"),
                "forks": data.get("forks_count"),
                "open_issues_count": data.get("open_issues_count"),
                "topics": data.get("topics", []),
                "license": (data.get("license") or {}).get("spdx_id") if isinstance(data.get("license"), dict) else None,
                "permissions": data.get("permissions"),
            }
        )
        return result

    @staticmethod
    def _issue_summary(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "author": _user(data.get("user")),
            "assignees": [_user(x) for x in data.get("assignees", []) if _user(x)],
            "labels": _labels(data.get("labels")),
            "comments": data.get("comments"),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "html_url": data.get("html_url"),
            "body_excerpt": _excerpt(data.get("body"), 1200),
        }

    @classmethod
    def _issue_detail(cls, data: dict[str, Any]) -> dict[str, Any]:
        result = cls._issue_summary(data)
        result.update(
            {
                "body": _excerpt(data.get("body"), 12000),
                "closed_at": data.get("closed_at"),
                "milestone": (data.get("milestone") or {}).get("title") if isinstance(data.get("milestone"), dict) else None,
                "locked": data.get("locked"),
            }
        )
        result.pop("body_excerpt", None)
        return result

    @staticmethod
    def _pull_summary(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "number": data.get("number"),
            "title": data.get("title"),
            "state": data.get("state"),
            "draft": data.get("draft"),
            "author": _user(data.get("user")),
            "head": (data.get("head") or {}).get("ref") if isinstance(data.get("head"), dict) else None,
            "base": (data.get("base") or {}).get("ref") if isinstance(data.get("base"), dict) else None,
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "html_url": data.get("html_url"),
        }

    @classmethod
    def _pull_detail(cls, data: dict[str, Any]) -> dict[str, Any]:
        result = cls._pull_summary(data)
        result.update(
            {
                "body": _excerpt(data.get("body"), 12000),
                "merged": data.get("merged"),
                "mergeable": data.get("mergeable"),
                "mergeable_state": data.get("mergeable_state"),
                "merged_at": data.get("merged_at"),
                "merged_by": _user(data.get("merged_by")),
                "commits": data.get("commits"),
                "additions": data.get("additions"),
                "deletions": data.get("deletions"),
                "changed_files": data.get("changed_files"),
                "comments": data.get("comments"),
                "review_comments": data.get("review_comments"),
                "labels": _labels(data.get("labels")),
                "requested_reviewers": [_user(x) for x in data.get("requested_reviewers", []) if _user(x)],
            }
        )
        return result

    @staticmethod
    def _commit_summary(data: dict[str, Any]) -> dict[str, Any]:
        commit = data.get("commit") if isinstance(data.get("commit"), dict) else {}
        author_meta = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        return {
            "sha": data.get("sha"),
            "message": commit.get("message"),
            "author": _user(data.get("author")) or author_meta.get("name"),
            "author_email": author_meta.get("email"),
            "date": author_meta.get("date"),
            "html_url": data.get("html_url"),
        }

    @staticmethod
    def _content_entry(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": data.get("type"),
            "name": data.get("name"),
            "path": data.get("path"),
            "sha": data.get("sha"),
            "size": data.get("size"),
            "html_url": data.get("html_url"),
        }

    @staticmethod
    def _code_summary(data: dict[str, Any]) -> dict[str, Any]:
        repo = data.get("repository") if isinstance(data.get("repository"), dict) else {}
        return {
            "name": data.get("name"),
            "path": data.get("path"),
            "sha": data.get("sha"),
            "repository": repo.get("full_name"),
            "html_url": data.get("html_url"),
        }

    @staticmethod
    def _workflow_run_summary(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": data.get("id"),
            "name": data.get("name"),
            "display_title": data.get("display_title"),
            "event": data.get("event"),
            "status": data.get("status"),
            "conclusion": data.get("conclusion"),
            "workflow_id": data.get("workflow_id"),
            "run_number": data.get("run_number"),
            "head_branch": data.get("head_branch"),
            "head_sha": data.get("head_sha"),
            "actor": _user(data.get("actor")),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "html_url": data.get("html_url"),
        }

    @staticmethod
    def _status_summary(data: dict[str, Any]) -> dict[str, Any]:
        return {
            "state": data.get("state"),
            "context": data.get("context"),
            "description": data.get("description"),
            "target_url": data.get("target_url"),
            "creator": _user(data.get("creator")),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
        }
