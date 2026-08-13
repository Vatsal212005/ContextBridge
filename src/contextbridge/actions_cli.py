"""Out-of-band human approval CLI for ContextBridge pending actions.

This command is deliberately separate from the MCP surface so an AI client cannot
approve its own mutation request. Approval is interactive and bound to the exact
signed action already persisted in SQLite. Milestone 8 also offers the same human
decision path through the localhost dashboard; neither channel is exposed as MCP.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from contextbridge.telemetry.instrumentation import get_telemetry_store


def _print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False, default=str))


def _compact_action(action: dict[str, Any]) -> dict[str, Any]:
    return {
        "action_id": action.get("action_id"),
        "status": action.get("status"),
        "tool_name": action.get("tool_name"),
        "risk_level": action.get("risk_level"),
        "arguments": action.get("arguments"),
        "requested_at": action.get("requested_at"),
        "expires_at": action.get("expires_at"),
        "requested_by": action.get("requested_by"),
        "decided_at": action.get("decided_at"),
        "decided_by": action.get("decided_by"),
        "decision_reason": action.get("decision_reason"),
        "signature_valid": action.get("signature_valid"),
        "approval_valid": action.get("approval_valid"),
        "execution_result": action.get("execution_result"),
        "execution_error_type": action.get("execution_error_type"),
        "execution_error_message": action.get("execution_error_message"),
    }


async def _list(status: str | None, limit: int) -> int:
    store = get_telemetry_store()
    actions = await store.list_pending_actions(status=status, limit=limit)
    _print_json([_compact_action(item) for item in actions])
    return 0


async def _show(action_id: str) -> int:
    store = get_telemetry_store()
    action = await store.get_pending_action(action_id)
    if action is None:
        print(f"Action {action_id!r} was not found.", file=sys.stderr)
        return 2
    _print_json(_compact_action(action))
    return 0


async def _decide(action_id: str, *, approve: bool, reason: str | None) -> int:
    store = get_telemetry_store()
    action = await store.get_pending_action(action_id)
    if action is None:
        print(f"Action {action_id!r} was not found.", file=sys.stderr)
        return 2

    print("\nExact signed action:\n")
    _print_json(_compact_action(action))
    print()

    if not action.get("signature_valid"):
        print("REFUSED: action signature is invalid.", file=sys.stderr)
        return 3
    if action.get("status") not in {"pending", "approved"}:
        print(
            f"REFUSED: action status is {action.get('status')!r}; it is not decidable.",
            file=sys.stderr,
        )
        return 3

    if approve:
        expected = "APPROVE"
        prompt = "Type APPROVE to approve this exact action once: "
    else:
        expected = "REJECT"
        prompt = "Type REJECT to reject this action: "

    try:
        typed = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nNo decision recorded.", file=sys.stderr)
        return 130
    if typed != expected:
        print("Decision cancelled; no state was changed.")
        return 1

    result = await store.decide_pending_action(
        action_id=action_id,
        approve=approve,
        actor="human:local_cli",
        reason=reason,
    )
    _print_json(_compact_action(result) if result.get("action_id") else result)
    if not result.get("ok"):
        return 3
    print(
        f"\n{'Approved' if approve else 'Rejected'} {action_id}."
        + (
            " The AI/MCP client may now call execute_approved_action once."
            if approve
            else " The action cannot be executed."
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="contextbridge-actions",
        description="Human-only ContextBridge pending-action approval CLI",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List pending/decided actions")
    p_list.add_argument(
        "--status",
        choices=[
            "pending",
            "approved",
            "rejected",
            "expired",
            "executing",
            "simulated",
            "executed",
            "failed",
        ],
        default=None,
    )
    p_list.add_argument("--limit", type=int, default=50)

    p_show = sub.add_parser("show", help="Show one exact action")
    p_show.add_argument("action_id")

    p_approve = sub.add_parser("approve", help="Interactively approve one exact action")
    p_approve.add_argument("action_id")
    p_approve.add_argument("--reason")

    p_reject = sub.add_parser("reject", help="Interactively reject one action")
    p_reject.add_argument("action_id")
    p_reject.add_argument("--reason")

    return parser


async def _main_async(args: argparse.Namespace) -> int:
    if args.command == "list":
        return await _list(args.status, args.limit)
    if args.command == "show":
        return await _show(args.action_id)
    if args.command == "approve":
        return await _decide(args.action_id, approve=True, reason=args.reason)
    if args.command == "reject":
        return await _decide(args.action_id, approve=False, reason=args.reason)
    raise RuntimeError("unknown command")


def main() -> None:
    args = build_parser().parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
