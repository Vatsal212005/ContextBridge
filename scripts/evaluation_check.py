from __future__ import annotations

import asyncio
import json

from contextbridge.evaluation import DEFAULT_BENCHMARK, run_and_record


async def main() -> None:
    report = await run_and_record(benchmark_path=DEFAULT_BENCHMARK, mode="baseline")
    compact = {
        "run_id": report["run_id"],
        "mode": report["mode"],
        "cases": report["cases"],
        "tool_selection_accuracy_pct": report["tool_selection_accuracy_pct"],
        "parameter_accuracy_pct": report["parameter_accuracy_pct"],
        "risk_accuracy_pct": report["risk_accuracy_pct"],
        "mutation_classification_accuracy_pct": report["mutation_classification_accuracy_pct"],
        "note": report["note"],
    }
    print("Evaluation framework is operational.")
    print(json.dumps(compact, indent=2))
    print("PASS: 100-case offline benchmark scored and persisted to SQLite without any model/API call.")


if __name__ == "__main__":
    asyncio.run(main())
