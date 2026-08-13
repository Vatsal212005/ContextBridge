"""Fail-closed write authorization policy for ContextBridge."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from contextbridge.config import Settings


class RiskLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"


# Only these mutation capabilities exist in Milestone 5. Repository/code/admin
# mutation tools are intentionally absent from this allowlist and the MCP server.
MUTATION_RISKS: dict[str, RiskLevel] = {
    "create_issue": RiskLevel.WRITE,
    "add_issue_comment": RiskLevel.WRITE,
    "add_labels": RiskLevel.WRITE,
    "close_issue": RiskLevel.DESTRUCTIVE,
    "reopen_issue": RiskLevel.WRITE,
}

PROHIBITED_CAPABILITIES = (
    "delete_repository",
    "delete_file",
    "create_or_update_file",
    "push_commit",
    "delete_branch",
    "force_push",
    "merge_pull_request",
    "modify_repository_settings",
    "modify_workflow",
)


@dataclass(frozen=True, slots=True)
class WritePolicyDecision:
    allowed: bool
    tool_name: str
    risk_level: str
    repository: str
    reason: str
    dry_run: bool
    writes_enabled: bool
    repository_authorized: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "tool_name": self.tool_name,
            "risk_level": self.risk_level,
            "repository": self.repository,
            "reason": self.reason,
            "gates": {
                "dry_run": self.dry_run,
                "writes_enabled": self.writes_enabled,
                "repository_authorized": self.repository_authorized,
            },
        }


def _repo_key(owner: str, repo: str) -> str:
    return f"{owner.strip()}/{repo.strip()}".lower()


def evaluate_write_policy(
    *,
    settings: Settings,
    tool_name: str,
    risk_level: RiskLevel,
    owner: str,
    repo: str,
) -> WritePolicyDecision:
    """Evaluate all fail-closed gates before any GitHub mutation request."""
    repository = f"{owner.strip()}/{repo.strip()}"
    expected_risk = MUTATION_RISKS.get(tool_name)
    authorized_repos = {item.lower() for item in settings.github_write_repositories}
    repo_authorized = _repo_key(owner, repo) in authorized_repos

    if expected_risk is None:
        return WritePolicyDecision(
            allowed=False,
            tool_name=tool_name,
            risk_level=risk_level.value,
            repository=repository,
            reason="tool_not_authorized_for_mutation",
            dry_run=settings.dry_run,
            writes_enabled=settings.github_writes_enabled,
            repository_authorized=repo_authorized,
        )

    if expected_risk != risk_level:
        return WritePolicyDecision(
            allowed=False,
            tool_name=tool_name,
            risk_level=risk_level.value,
            repository=repository,
            reason="risk_classification_mismatch",
            dry_run=settings.dry_run,
            writes_enabled=settings.github_writes_enabled,
            repository_authorized=repo_authorized,
        )

    # DRY_RUN is the first and strongest runtime gate. In Milestone 5 it is on
    # by default, so mutation tools produce a preview without sending a mutation.
    if settings.dry_run:
        reason = "dry_run_enabled"
        allowed = False
    elif not settings.github_writes_enabled:
        reason = "writes_disabled"
        allowed = False
    elif not repo_authorized:
        reason = "repository_not_authorized"
        allowed = False
    else:
        reason = "authorized"
        allowed = True

    return WritePolicyDecision(
        allowed=allowed,
        tool_name=tool_name,
        risk_level=risk_level.value,
        repository=repository,
        reason=reason,
        dry_run=settings.dry_run,
        writes_enabled=settings.github_writes_enabled,
        repository_authorized=repo_authorized,
    )
