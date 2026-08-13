from __future__ import annotations

from pathlib import Path

from contextbridge.config import Settings
from contextbridge.security.policy import RiskLevel, evaluate_write_policy


def _settings(**overrides):
    base = dict(
        github_token="test",
        database_path=Path("data/test.db"),
        dry_run=True,
        github_writes_enabled=False,
        github_write_repositories=(),
    )
    base.update(overrides)
    return Settings(**base)


def test_dry_run_blocks_even_when_other_gates_open() -> None:
    decision = evaluate_write_policy(
        settings=_settings(
            dry_run=True,
            github_writes_enabled=True,
            github_write_repositories=("owner/repo",),
        ),
        tool_name="create_issue",
        risk_level=RiskLevel.WRITE,
        owner="owner",
        repo="repo",
    )
    assert decision.allowed is False
    assert decision.reason == "dry_run_enabled"


def test_writes_disabled_is_second_gate() -> None:
    decision = evaluate_write_policy(
        settings=_settings(
            dry_run=False,
            github_writes_enabled=False,
            github_write_repositories=("owner/repo",),
        ),
        tool_name="create_issue",
        risk_level=RiskLevel.WRITE,
        owner="owner",
        repo="repo",
    )
    assert decision.allowed is False
    assert decision.reason == "writes_disabled"


def test_repository_allowlist_is_third_gate() -> None:
    decision = evaluate_write_policy(
        settings=_settings(dry_run=False, github_writes_enabled=True),
        tool_name="create_issue",
        risk_level=RiskLevel.WRITE,
        owner="owner",
        repo="repo",
    )
    assert decision.allowed is False
    assert decision.reason == "repository_not_authorized"


def test_all_three_runtime_gates_required() -> None:
    decision = evaluate_write_policy(
        settings=_settings(
            dry_run=False,
            github_writes_enabled=True,
            github_write_repositories=("Owner/Repo",),
        ),
        tool_name="create_issue",
        risk_level=RiskLevel.WRITE,
        owner="owner",
        repo="repo",
    )
    assert decision.allowed is True
    assert decision.reason == "authorized"


def test_risk_mismatch_fails_closed() -> None:
    decision = evaluate_write_policy(
        settings=_settings(
            dry_run=False,
            github_writes_enabled=True,
            github_write_repositories=("owner/repo",),
        ),
        tool_name="close_issue",
        risk_level=RiskLevel.WRITE,
        owner="owner",
        repo="repo",
    )
    assert decision.allowed is False
    assert decision.reason == "risk_classification_mismatch"
