"""Human-confirmed GitHub issue mutation tools for ContextBridge Milestone 6.

Mutation request tools NEVER call GitHub directly. They persist an exact, signed
pending action and return its action_id. Approval/rejection is intentionally not
exposed as MCP tools; the human must decide out-of-band through the local CLI or
localhost dashboard.
Only execute_approved_action can reach GitHub, and it still obeys the Milestone 5
fail-closed dry-run/write-enable/repository-allowlist policy.
"""

from __future__ import annotations

import re
from typing import Any

from contextbridge.config import settings
from contextbridge.github.client import GitHubClient
from contextbridge.github.errors import GitHubError
from contextbridge.github.write_api import GitHubWriteAPI
from contextbridge.security.policy import (
    MUTATION_RISKS,
    PROHIBITED_CAPABILITIES,
    RiskLevel,
    evaluate_write_policy,
)
from contextbridge.telemetry.instrumentation import get_telemetry_store, observed_tool

_OWNER_REPO = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_repository(owner: str, repo: str) -> None:
    if not owner or not repo or not _OWNER_REPO.fullmatch(owner) or not _OWNER_REPO.fullmatch(repo):
        raise ValueError("owner and repo must be non-empty GitHub-safe names")


def _validate_issue_number(issue_number: int) -> None:
    if issue_number < 1:
        raise ValueError("issue_number must be at least 1")


def _client() -> GitHubClient:
    return GitHubClient(
        token=settings.github_token,
        base_url=settings.github_api_url,
        api_version=settings.github_api_version,
        timeout_seconds=settings.github_timeout_seconds,
        max_retries=settings.github_max_retries,
    )


def _preview(tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {"tool": tool_name, "arguments": arguments}


def _action_view(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "tool_name": action.get("tool_name"),
        "risk_level": action.get("risk_level"),
        "status": action.get("status"),
        "requested_at": action.get("requested_at"),
        "expires_at": action.get("expires_at"),
        "requested_by": action.get("requested_by"),
        "decided_at": action.get("decided_at"),
        "decided_by": action.get("decided_by"),
        "decision_reason": action.get("decision_reason"),
        "signature_valid": action.get("signature_valid"),
        "approval_valid": action.get("approval_valid"),
        "deduplicated": action.get("deduplicated", False),
        "arguments": action.get("arguments", {}),
        "execution_result": action.get("execution_result"),
        "execution_error_type": action.get("execution_error_type"),
        "execution_error_message": action.get("execution_error_message"),
    }


async def _request_mutation(
    *,
    tool_name: str,
    risk_level: RiskLevel,
    owner: str,
    repo: str,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Persist an exact mutation request without constructing a GitHub client."""
    _validate_repository(owner, repo)
    expected_risk = MUTATION_RISKS.get(tool_name)
    if expected_risk is None or expected_risk != risk_level:
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "error": {
                "type": "mutation_not_authorized",
                "message": "Tool is not authorized by the mutation registry.",
                "retryable": False,
            },
        }

    action = await get_telemetry_store().create_pending_action(
        tool_name=tool_name,
        risk_level=risk_level.value,
        arguments=arguments,
        ttl_minutes=settings.confirmation_ttl_minutes,
        requested_by="mcp_client",
    )
    action_id = str(action["action_id"])
    return {
        "ok": False,
        "status": "confirmation_required",
        "confirmation_required": True,
        "github_request_sent": False,
        "action": _action_view(action),
        "preview": _preview(tool_name, arguments),
        "human_confirmation": {
            "approval_channel": "local_cli_or_dashboard",
            "mcp_approval_available": False,
            "approve_command": (
                f".\\.venv\\Scripts\\python.exe scripts\\action_cli.py approve {action_id}"
            ),
            "reject_command": (
                f".\\.venv\\Scripts\\python.exe scripts\\action_cli.py reject {action_id}"
            ),
            "next_step": (
                "A human must approve this exact signed action out-of-band. "
                "After approval, call execute_approved_action with the action_id."
            ),
        },
    }


async def _run_stored_operation(api: GitHubWriteAPI, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    owner = str(args["owner"])
    repo = str(args["repo"])
    _validate_repository(owner, repo)

    if tool_name == "create_issue":
        title = str(args["title"])
        body = args.get("body")
        return await api.create_issue(owner=owner, repo=repo, title=title, body=body)
    if tool_name == "add_issue_comment":
        issue_number = int(args["issue_number"])
        _validate_issue_number(issue_number)
        return await api.add_issue_comment(
            owner=owner, repo=repo, issue_number=issue_number, body=str(args["body"])
        )
    if tool_name == "add_labels":
        issue_number = int(args["issue_number"])
        _validate_issue_number(issue_number)
        labels = [str(item) for item in args["labels"]]
        return await api.add_labels(
            owner=owner, repo=repo, issue_number=issue_number, labels=labels
        )
    if tool_name == "close_issue":
        issue_number = int(args["issue_number"])
        _validate_issue_number(issue_number)
        return await api.close_issue(owner=owner, repo=repo, issue_number=issue_number)
    if tool_name == "reopen_issue":
        issue_number = int(args["issue_number"])
        _validate_issue_number(issue_number)
        return await api.reopen_issue(owner=owner, repo=repo, issue_number=issue_number)
    raise ValueError("Stored action references an unsupported mutation tool.")


@observed_tool(risk_level="read")
async def get_write_policy() -> dict[str, Any]:
    """Inspect mutation gates and human-confirmation requirements without changing anything."""
    return {
        "ok": True,
        "dry_run": settings.dry_run,
        "github_writes_enabled": settings.github_writes_enabled,
        "authorized_write_repositories": list(settings.github_write_repositories),
        "confirmation_ttl_minutes": settings.confirmation_ttl_minutes,
        "human_confirmation": {
            "required_for_every_mutation": True,
            "approval_channel": "local_cli_or_dashboard",
            "approval_exposed_as_mcp_tool": False,
            "one_time_execution_claim": True,
            "signed_action_records": True,
        },
        "mutation_tools": {name: risk.value for name, risk in MUTATION_RISKS.items()},
        "prohibited_capabilities_not_implemented": list(PROHIBITED_CAPABILITIES),
        "live_write_requires_all": [
            "exact pending action approved out-of-band by a human",
            "unexpired action signature must verify",
            "CONTEXTBRIDGE_DRY_RUN=false",
            "GITHUB_WRITES_ENABLED=true",
            "target repository explicitly listed in GITHUB_WRITE_REPOSITORIES",
            "GitHub token with only the minimum Issues: write permission",
        ],
        "milestone_8_mode": (
            "6B remains intentionally skipped: keep DRY_RUN=true and GITHUB_WRITES_ENABLED=false. "
            "Approved actions are simulated and never sent to GitHub. Human approval may occur through "
            "the local CLI or the localhost dashboard, never through MCP."
        ),
    }


@observed_tool(risk_level="read")
async def list_pending_actions(status: str | None = None, limit: int = 25) -> dict[str, Any]:
    """List human-confirmation actions. This tool cannot approve or reject them."""
    items = await get_telemetry_store().list_pending_actions(status=status, limit=limit)
    return {"ok": True, "count": len(items), "actions": [_action_view(item) for item in items]}


@observed_tool(risk_level="read")
async def get_pending_action(action_id: str) -> dict[str, Any]:
    """Inspect one pending/decided action by ID without changing its state."""
    action_id = action_id.strip()
    if not action_id:
        raise ValueError("action_id is required")
    item = await get_telemetry_store().get_pending_action(action_id)
    if item is None:
        return {"ok": False, "status": "not_found", "action_id": action_id}
    return {"ok": True, "action": _action_view(item)}


@observed_tool(risk_level="destructive")
async def execute_approved_action(action_id: str) -> dict[str, Any]:
    """Execute exactly one human-approved action; DRY_RUN simulates without contacting GitHub."""
    action_id = action_id.strip()
    if not action_id:
        raise ValueError("action_id is required")

    store = get_telemetry_store()
    action = await store.get_pending_action(action_id)
    if action is None:
        return {"ok": False, "status": "not_found", "action_id": action_id}
    if not action.get("signature_valid"):
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "action_id": action_id,
            "error": {
                "type": "action_signature_invalid",
                "message": "Pending action integrity verification failed.",
                "retryable": False,
            },
        }
    if action["status"] == "pending":
        return {
            "ok": False,
            "status": "confirmation_required",
            "confirmation_required": True,
            "action": _action_view(action),
            "message": "Action is still waiting for out-of-band human approval.",
        }
    if action["status"] != "approved":
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "action": _action_view(action),
            "error": {
                "type": "action_not_executable",
                "message": f"Action status is {action['status']!r}, not 'approved'.",
                "retryable": False,
            },
        }

    tool_name = str(action["tool_name"])
    args = dict(action["arguments"])
    risk = MUTATION_RISKS.get(tool_name)
    if risk is None or risk.value != action["risk_level"]:
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "error": {
                "type": "mutation_registry_mismatch",
                "message": "Stored action no longer matches the authorized mutation registry.",
                "retryable": False,
            },
        }

    owner = str(args.get("owner") or "")
    repo = str(args.get("repo") or "")
    _validate_repository(owner, repo)

    # Milestone 6A: an approved action is consumed exactly once, but dry-run
    # execution only records a simulation. No GitHub client is constructed.
    if settings.dry_run:
        claimed = await store.claim_approved_action(action_id)
        if not claimed.get("ok"):
            return claimed
        simulated_result = {
            "tool": tool_name,
            "arguments": args,
            "github_request_sent": False,
            "reason": "CONTEXTBRIDGE_DRY_RUN=true",
        }
        finalized = await store.finalize_action(
            action_id=action_id,
            status="simulated",
            result=simulated_result,
            actor="mcp_client",
        )
        return {
            "ok": True,
            "status": "simulated",
            "dry_run": True,
            "github_request_sent": False,
            "action": _action_view(finalized),
            "simulation": simulated_result,
        }

    # Future live mode remains independently gated by the Milestone 5 policy.
    decision = evaluate_write_policy(
        settings=settings,
        tool_name=tool_name,
        risk_level=risk,
        owner=owner,
        repo=repo,
    )
    if not decision.allowed:
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "github_request_sent": False,
            "policy": decision.as_dict(),
            "error": {
                "type": "write_policy_blocked",
                "message": f"Approved action was not sent. Policy reason: {decision.reason}.",
                "retryable": False,
            },
        }
    if not settings.github_token:
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "github_request_sent": False,
            "error": {
                "type": "not_configured",
                "message": "GITHUB_TOKEN is not configured.",
                "retryable": False,
            },
        }

    claimed = await store.claim_approved_action(action_id)
    if not claimed.get("ok"):
        return claimed

    client = _client()
    try:
        result = await _run_stored_operation(GitHubWriteAPI(client), tool_name, args)
        finalized = await store.finalize_action(
            action_id=action_id,
            status="executed",
            result=result,
            actor="mcp_client",
        )
        return {
            "ok": True,
            "status": "executed",
            "github_request_sent": True,
            "policy": decision.as_dict(),
            "action": _action_view(finalized),
            "result": result,
        }
    except GitHubError as exc:
        await store.finalize_action(
            action_id=action_id,
            status="failed",
            error_type=exc.kind,
            error_message=str(exc),
            actor="mcp_client",
        )
        return {
            "ok": False,
            "status": "error",
            "github_request_sent": True,
            "error": exc.as_dict(),
            "policy": decision.as_dict(),
        }
    except ValueError as exc:
        await store.finalize_action(
            action_id=action_id,
            status="failed",
            error_type="safety_validation_failed",
            error_message=str(exc),
            actor="mcp_client",
        )
        return {
            "ok": False,
            "status": "blocked",
            "blocked": True,
            "github_request_sent": False,
            "error": {
                "type": "safety_validation_failed",
                "message": str(exc),
                "retryable": False,
            },
            "policy": decision.as_dict(),
        }
    finally:
        await client.aclose()


@observed_tool(risk_level="write")
async def create_issue(owner: str, repo: str, title: str, body: str | None = None) -> dict[str, Any]:
    """Request creation of a GitHub issue; queues exact action for human approval."""
    title = title.strip()
    if not title or len(title) > 256:
        raise ValueError("title must contain 1-256 characters")
    if body is not None and len(body) > 65_536:
        raise ValueError("body must be at most 65536 characters")
    args = {"owner": owner, "repo": repo, "title": title, "body": body}
    return await _request_mutation(
        tool_name="create_issue",
        risk_level=RiskLevel.WRITE,
        owner=owner,
        repo=repo,
        arguments=args,
    )


@observed_tool(risk_level="write")
async def add_issue_comment(owner: str, repo: str, issue_number: int, body: str) -> dict[str, Any]:
    """Request an issue comment; queues exact action for human approval."""
    _validate_issue_number(issue_number)
    body = body.strip()
    if not body or len(body) > 65_536:
        raise ValueError("body must contain 1-65536 characters")
    args = {"owner": owner, "repo": repo, "issue_number": issue_number, "body": body}
    return await _request_mutation(
        tool_name="add_issue_comment",
        risk_level=RiskLevel.WRITE,
        owner=owner,
        repo=repo,
        arguments=args,
    )


@observed_tool(risk_level="write")
async def add_labels(owner: str, repo: str, issue_number: int, labels: list[str]) -> dict[str, Any]:
    """Request existing labels be added to an issue; queues exact action for human approval."""
    _validate_issue_number(issue_number)
    cleaned = [label.strip() for label in labels if label.strip()]
    if not cleaned or len(cleaned) > 20:
        raise ValueError("labels must contain between 1 and 20 non-empty labels")
    if any(len(label) > 100 for label in cleaned):
        raise ValueError("each label must be at most 100 characters")
    args = {"owner": owner, "repo": repo, "issue_number": issue_number, "labels": cleaned}
    return await _request_mutation(
        tool_name="add_labels",
        risk_level=RiskLevel.WRITE,
        owner=owner,
        repo=repo,
        arguments=args,
    )


@observed_tool(risk_level="destructive")
async def close_issue(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
    """Request closure of an issue; destructive action always requires human approval."""
    _validate_issue_number(issue_number)
    args = {"owner": owner, "repo": repo, "issue_number": issue_number}
    return await _request_mutation(
        tool_name="close_issue",
        risk_level=RiskLevel.DESTRUCTIVE,
        owner=owner,
        repo=repo,
        arguments=args,
    )


@observed_tool(risk_level="write")
async def reopen_issue(owner: str, repo: str, issue_number: int) -> dict[str, Any]:
    """Request reopening of an issue; queues exact action for human approval."""
    _validate_issue_number(issue_number)
    args = {"owner": owner, "repo": repo, "issue_number": issue_number}
    return await _request_mutation(
        tool_name="reopen_issue",
        risk_level=RiskLevel.WRITE,
        owner=owner,
        repo=repo,
        arguments=args,
    )
