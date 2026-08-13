"""GitHub integration package."""

from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubError

__all__ = ["GitHubClient", "GitHubError"]
