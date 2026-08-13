"""Provider-agnostic offline evaluation harness for ContextBridge tool selection.

The default baseline is deliberately a deterministic keyword router. It is a smoke test for the
benchmark/scoring pipeline, not an LLM quality claim. To evaluate an actual model/MCP host, export
its predicted tool calls as JSON and pass them with --predictions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from contextbridge.telemetry.instrumentation import get_telemetry_store

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BENCHMARK = Path(__file__).resolve().parent / "eval_data" / "tool_selection.json"

TOOL_RISKS: dict[str, str] = {
    "server_info": "read",
    "health": "read",
    "github_connection_status": "read",
    "list_repositories": "read",
    "get_repository": "read",
    "search_issues": "read",
    "get_issue": "read",
    "list_pull_requests": "read",
    "get_pull_request": "read",
    "list_commits": "read",
    "get_file_contents": "read",
    "search_code": "read",
    "get_workflow_runs": "read",
    "get_commit_status": "read",
    "get_tool_metrics": "read",
    "get_recent_tool_calls": "read",
    "get_audit_summary": "read",
    "get_write_policy": "read",
    "list_pending_actions": "read",
    "get_pending_action": "read",
    "execute_approved_action": "destructive",
    "create_issue": "write",
    "add_issue_comment": "write",
    "add_labels": "write",
    "close_issue": "destructive",
    "reopen_issue": "write",
    "get_evaluation_summary": "read",
}
MUTATING_TOOLS = {
    "execute_approved_action",
    "create_issue",
    "add_issue_comment",
    "add_labels",
    "close_issue",
    "reopen_issue",
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _owner_repo(prompt: str) -> tuple[str, str] | None:
    matches = re.findall(r"\b([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)\b", prompt)
    if not matches:
        return None
    owner, repo = matches[0]
    return owner, repo.rstrip(".,;:!?")


def _number(prompt: str, noun: str) -> int | None:
    patterns = [rf"{noun}\s*#?\s*(\d+)", rf"#(\d+)"]
    for pattern in patterns:
        m = re.search(pattern, prompt, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    return None


def baseline_prediction(case: dict[str, Any]) -> dict[str, Any]:
    """Return a deterministic keyword baseline prediction for harness verification."""
    prompt = str(case["prompt"])
    p = prompt.lower()
    tool = "get_repository"

    if any(x in p for x in ["evaluation score", "latest evaluation", "benchmark result", "tool selection accuracy"]):
        tool = "get_evaluation_summary"
    elif any(x in p for x in ["write policy", "writes enabled", "dry run", "mutation policy"]):
        tool = "get_write_policy"
    elif "pending action" in p and any(x in p for x in ["list", "show all", "queue"]):
        tool = "list_pending_actions"
    elif "human confirmation queue" in p:
        tool = "list_pending_actions"
    elif "execute approved" in p or "run approved action" in p or ("approved action" in p and "run" in p) or ("execute" in p and "after approval" in p):
        tool = "execute_approved_action"
    elif "action id" in p or re.search(r"\bact_[A-Za-z0-9_-]+", prompt):
        tool = "get_pending_action"
    elif any(x in p for x in ["audit summary", "audit events", "audit log summary", "audit trail"]):
        tool = "get_audit_summary"
    elif any(x in p for x in ["recent tool calls", "last tool calls", "tool execution history", "recent mcp tool calls", "tool-call history"]):
        tool = "get_recent_tool_calls"
    elif any(x in p for x in ["tool metrics", "success rate", "average latency", "p95 latency"]):
        tool = "get_tool_metrics"
    elif any(x in p for x in ["github connection", "github account", "authenticated github", "rate limit remaining", "api rate limit"]):
        tool = "github_connection_status"
    elif ("reopen" in p or "open again" in p or re.search(r"\bopen\s+issue\s+#?\d+\s+again\b", p)) and "issue" in p:
        tool = "reopen_issue"
    elif re.search(r"\bclose\b", p) and "issue" in p:
        tool = "close_issue"
    elif ("comment" in p or "reply" in p or "add a note" in p) and "issue" in p:
        tool = "add_issue_comment"
    elif ("label" in p or "tag" in p) and "issue" in p and any(x in p for x in ["add", "apply", "tag", "mark"]):
        tool = "add_labels"
    elif any(x in p for x in ["create an issue", "create issue", "open an issue", "file a bug", "file an issue"]):
        tool = "create_issue"
    elif any(x in p for x in ["workflow run", "github actions", "actions run", "failed workflow", "ci runs"]):
        tool = "get_workflow_runs"
    elif any(x in p for x in ["commit status", "status contexts", "combined status"]):
        tool = "get_commit_status"
    elif ("pull request" in p or re.search(r"\bpr\b", p)) and ("#" in p or re.search(r"\b(?:pr|pull request)\s+\d+", p)):
        tool = "get_pull_request"
    elif ("pull request" in p or re.search(r"\bprs?\b", p)) and any(x in p for x in ["list", "show", "open", "closed", "recent"]):
        tool = "list_pull_requests"
    elif any(x in p for x in ["read file", "show file", "file contents", "open file", "directory contents", "readme", "pyproject.toml", "package.json"]):
        tool = "get_file_contents"
    elif ("search" in p or "find" in p) and any(x in p for x in ["code", "function", "class", "symbol", "implementation", "todo"]):
        tool = "search_code"
    elif "commit" in p:
        tool = "list_commits"
    elif "issue" in p and ("#" in p or re.search(r"\bissue\s+\d+", p)):
        tool = "get_issue"
    elif any(x in p for x in ["issues", "bugs", "issue"] ) and any(x in p for x in ["search", "find", "list", "show", "assigned", "across", "unresolved", "open"]):
        tool = "search_issues"
    elif any(x in p for x in ["list repositories", "list repos", "my repositories", "repos can", "repositories can", "visible repositories", "accessible repos"]):
        tool = "list_repositories"
    elif any(x in p for x in ["repository metadata", "repo metadata", "repository details", "default branch", "about repo", "about repository"]):
        tool = "get_repository"

    args: dict[str, Any] = {}
    pair = _owner_repo(prompt)
    if pair:
        args["owner"], args["repo"] = pair
    if tool in {"get_issue", "add_issue_comment", "add_labels", "close_issue", "reopen_issue"}:
        n = _number(prompt, "issue")
        if n is not None:
            args["issue_number"] = n
    if tool == "get_pull_request":
        n = _number(prompt, r"(?:pr|pull request)")
        if n is not None:
            args["pull_number"] = n
    if tool == "execute_approved_action" or tool == "get_pending_action":
        m = re.search(r"\b(act_[A-Za-z0-9_-]+)\b", prompt)
        if m:
            args["action_id"] = m.group(1)
    if tool == "search_issues":
        if "closed" in p:
            args["state"] = "closed"
        elif "open" in p or "unresolved" in p:
            args["state"] = "open"
    return {"id": case["id"], "actual_tool": tool, "actual_arguments": args}


def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return value.strip().lower()
    if isinstance(value, list):
        return sorted(_norm(v) for v in value)
    if isinstance(value, dict):
        return {str(k): _norm(v) for k, v in value.items()}
    return value


def _parameter_score(expected: dict[str, Any], actual: dict[str, Any] | None) -> float | None:
    if not expected:
        return None
    actual = actual or {}
    matched = sum(1 for key, value in expected.items() if key in actual and _norm(actual[key]) == _norm(value))
    return matched / len(expected)


def score_cases(cases: list[dict[str, Any]], predictions: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_id = {str(p.get("id")): p for p in predictions}
    correct_tools = 0
    missing = 0
    parameter_scores: list[float] = []
    risk_total = risk_correct = 0
    mutation_total = mutation_correct = 0
    confusion: Counter[tuple[str, str]] = Counter()
    per_tool: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    results: list[dict[str, Any]] = []

    for case in cases:
        expected_tool = str(case["expected_tool"])
        expected_risk = str(case.get("risk") or TOOL_RISKS.get(expected_tool, "read"))
        pred = by_id.get(str(case["id"]))
        actual_tool = str(pred.get("actual_tool")) if pred and pred.get("actual_tool") else None
        actual_args = pred.get("actual_arguments") if pred and isinstance(pred.get("actual_arguments"), dict) else {}
        tool_correct = actual_tool == expected_tool
        per_tool[expected_tool][1] += 1
        if pred is None or actual_tool is None:
            missing += 1
        elif tool_correct:
            correct_tools += 1
            per_tool[expected_tool][0] += 1
        else:
            confusion[(expected_tool, actual_tool)] += 1

        pscore = _parameter_score(case.get("expected_arguments") or {}, actual_args)
        if pscore is not None:
            parameter_scores.append(pscore)

        actual_risk = TOOL_RISKS.get(actual_tool) if actual_tool else None
        rcorrect = None
        if actual_tool:
            risk_total += 1
            rcorrect = actual_risk == expected_risk
            if rcorrect:
                risk_correct += 1

        confirmation_required = bool(case.get("confirmation_required", expected_tool in MUTATING_TOOLS))
        mcorrect = None
        if actual_tool:
            mutation_total += 1
            mcorrect = (actual_tool in MUTATING_TOOLS) == confirmation_required
            if mcorrect:
                mutation_correct += 1

        results.append({
            "id": str(case["id"]),
            "prompt": str(case["prompt"]),
            "expected_tool": expected_tool,
            "actual_tool": actual_tool,
            "tool_correct": tool_correct,
            "expected_arguments": case.get("expected_arguments") or {},
            "actual_arguments": actual_args,
            "parameter_score": None if pscore is None else round(pscore, 4),
            "expected_risk": expected_risk,
            "actual_risk": actual_risk,
            "risk_correct": rcorrect,
            "confirmation_required": confirmation_required,
            "mutation_classification_correct": mcorrect,
        })

    total = len(cases)
    provided = total - missing
    report = {
        "benchmark": "contextbridge-tool-selection-v1",
        "cases": total,
        "predictions_received": provided,
        "missing_predictions": missing,
        "tool_selection_accuracy_pct": round(correct_tools / total * 100, 2) if total else 0.0,
        "selection_accuracy_on_provided_pct": round(correct_tools / provided * 100, 2) if provided else 0.0,
        "parameter_accuracy_pct": round(sum(parameter_scores) / len(parameter_scores) * 100, 2) if parameter_scores else None,
        "parameter_cases": len(parameter_scores),
        "risk_accuracy_pct": round(risk_correct / risk_total * 100, 2) if risk_total else None,
        "mutation_classification_accuracy_pct": round(mutation_correct / mutation_total * 100, 2) if mutation_total else None,
        "per_tool": {
            tool: {"correct": vals[0], "total": vals[1], "accuracy_pct": round(vals[0] / vals[1] * 100, 2) if vals[1] else 0.0}
            for tool, vals in sorted(per_tool.items())
        },
        "top_confusions": [
            {"expected": expected, "actual": actual, "count": count}
            for (expected, actual), count in confusion.most_common(12)
        ],
        "failure_sample": [row for row in results if not row["tool_correct"]][:20],
        "note": "The built-in baseline is a deterministic harness smoke test, not an LLM benchmark result.",
    }
    return report, results


async def run_and_record(*, benchmark_path: Path, mode: str, predictions_path: Path | None = None) -> dict[str, Any]:
    cases = load_json(benchmark_path)
    if not isinstance(cases, list):
        raise ValueError("Benchmark must be a JSON array.")
    if mode == "baseline":
        predictions = [baseline_prediction(case) for case in cases]
    elif mode == "predictions":
        if predictions_path is None:
            raise ValueError("predictions_path is required in predictions mode")
        predictions = load_json(predictions_path)
        if not isinstance(predictions, list):
            raise ValueError("Predictions must be a JSON array.")
    else:
        raise ValueError("mode must be baseline or predictions")

    report, results = score_cases(cases, predictions)
    run_id = await get_telemetry_store().record_evaluation_run(
        mode=mode,
        benchmark_name=benchmark_path.name,
        report=report,
        results=results,
    )
    report = {"run_id": run_id, "mode": mode, **report}
    return report


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run ContextBridge tool-selection evaluations")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", action="store_true", help="Run deterministic offline baseline")
    group.add_argument("--predictions", type=Path, help="JSON predictions exported from a model/MCP host")
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--out", type=Path, help="Optional JSON report output path")
    parser.add_argument("--no-record", action="store_true", help="Do not persist the run to SQLite")
    return parser


async def _main_async(args: argparse.Namespace) -> int:
    cases = load_json(args.benchmark)
    if args.baseline:
        predictions = [baseline_prediction(case) for case in cases]
        mode = "baseline"
    else:
        predictions = load_json(args.predictions)
        mode = "predictions"
    report, results = score_cases(cases, predictions)
    if not args.no_record:
        run_id = await get_telemetry_store().record_evaluation_run(
            mode=mode, benchmark_name=args.benchmark.name, report=report, results=results
        )
        report = {"run_id": run_id, "mode": mode, **report}
    rendered = json.dumps(report, indent=2, ensure_ascii=False)
    print(rendered)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return 0


def main() -> None:
    args = _parser().parse_args()
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
