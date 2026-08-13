"""Narrow GitHub issue-mutation API for ContextBridge.

This module contains no repository-content, branch, pull-request merge, workflow,
or repository-administration mutation methods.
"""

from __future__ import annotations

from typing import Any

from contextbridge.github.client import GitHubClient


class GitHubWriteAPI:
    """Issue-only GitHub mutations used after the policy layer authorizes them."""

    def __init__(self, client: GitHubClient) -> None:
        self.client = client

    async def _require_issue_not_pull_request(
        self, *, owner: str, repo: str, issue_number: int
    ) -> dict[str, Any]:
        response = await self.client.request(
            "GET", f"/repos/{owner}/{repo}/issues/{issue_number}"
        )
        issue = response.json()
        if "pull_request" in issue:
            raise ValueError(
                "This mutation surface is issue-only; pull request numbers are rejected."
            )
        return issue

    async def create_issue(
        self, *, owner: str, repo: str, title: str, body: str | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"title": title}
        if body is not None:
            payload["body"] = body
        response = await self.client.request(
            "POST", f"/repos/{owner}/{repo}/issues", json=payload
        )
        return _issue_result(response.json(), action="created")

    async def add_issue_comment(
        self, *, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        await self._require_issue_not_pull_request(
            owner=owner, repo=repo, issue_number=issue_number
        )
        response = await self.client.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
        )
        data = response.json()
        return {
            "action": "comment_added",
            "issue_number": issue_number,
            "comment_id": data.get("id"),
            "html_url": data.get("html_url"),
            "created_at": data.get("created_at"),
        }

    async def add_labels(
        self, *, owner: str, repo: str, issue_number: int, labels: list[str]
    ) -> dict[str, Any]:
        await self._require_issue_not_pull_request(
            owner=owner, repo=repo, issue_number=issue_number
        )
        response = await self.client.request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/labels",
            json={"labels": labels},
        )
        data = response.json()
        return {
            "action": "labels_added",
            "issue_number": issue_number,
            "labels": [item.get("name") for item in data if isinstance(item, dict)],
        }

    async def close_issue(
        self, *, owner: str, repo: str, issue_number: int
    ) -> dict[str, Any]:
        await self._require_issue_not_pull_request(
            owner=owner, repo=repo, issue_number=issue_number
        )
        response = await self.client.request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json={"state": "closed"},
        )
        return _issue_result(response.json(), action="closed")

    async def reopen_issue(
        self, *, owner: str, repo: str, issue_number: int
    ) -> dict[str, Any]:
        await self._require_issue_not_pull_request(
            owner=owner, repo=repo, issue_number=issue_number
        )
        response = await self.client.request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json={"state": "open"},
        )
        return _issue_result(response.json(), action="reopened")


def _issue_result(data: dict[str, Any], *, action: str) -> dict[str, Any]:
    return {
        "action": action,
        "number": data.get("number"),
        "title": data.get("title"),
        "state": data.get("state"),
        "html_url": data.get("html_url"),
        "updated_at": data.get("updated_at"),
    }
