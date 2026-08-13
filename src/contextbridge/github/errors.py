"""Normalized GitHub API errors exposed by the service layer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class GitHubError(Exception):
    """Base normalized GitHub error."""

    kind: str
    message: str
    status_code: int | None = None
    retryable: bool = False
    retry_after_seconds: float | None = None
    documentation_url: str | None = None
    request_id: str | None = None
    details: Any = None

    def __str__(self) -> str:
        return self.message

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.kind,
            "message": self.message,
            "status_code": self.status_code,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "documentation_url": self.documentation_url,
            "request_id": self.request_id,
        }


class GitHubAuthenticationError(GitHubError):
    pass


class GitHubPermissionError(GitHubError):
    pass


class GitHubNotFoundError(GitHubError):
    pass


class GitHubValidationError(GitHubError):
    pass


class GitHubRateLimitError(GitHubError):
    pass


class GitHubTransientError(GitHubError):
    pass
