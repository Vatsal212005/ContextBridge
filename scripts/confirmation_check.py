"""Exercise the full Milestone 6A confirmation lifecycle without contacting GitHub."""
from __future__ import annotations

import asyncio
import json
import uuid

from contextbridge.config import settings
from contextbridge.telemetry.instrumentation import get_telemetry_store
import contextbridge.tools.github_write as write_tools


def explode_client():
    raise AssertionError("GitHub client was constructed while DRY_RUN=true")


async def main() -> None:
    if settings.dry_run is not True or settings.github_writes_enabled is not False:
        raise SystemExit(
            "REFUSED: confirmation_check requires CONTEXTBRIDGE_DRY_RUN=true and "
            "GITHUB_WRITES_ENABLED=false."
        )

    store = get_telemetry_store()
    original_client = write_tools._client
    write_tools._client = explode_client
    marker = uuid.uuid4().hex[:10]
    try:
        requested = await write_tools.create_issue(
            "contextbridge-safety-test",
            "no-live-request",
            f"M6 approval simulation {marker}",
            "Verification only; GitHub must never receive this request.",
        )
        action_id = requested["action"]["action_id"]
        approved = await store.decide_pending_action(
            action_id=action_id,
            approve=True,
            actor="human:verification_script",
            reason="automated local verification invoked by repository owner",
        )
        simulated = await write_tools.execute_approved_action(action_id)

        rejected_req = await write_tools.create_issue(
            "contextbridge-safety-test",
            "no-live-request",
            f"M6 rejection simulation {marker}",
            "Verification only; this action is rejected.",
        )
        rejected_id = rejected_req["action"]["action_id"]
        rejected = await store.decide_pending_action(
            action_id=rejected_id,
            approve=False,
            actor="human:verification_script",
            reason="rejection path verification",
        )
        rejected_execute = await write_tools.execute_approved_action(rejected_id)
    finally:
        write_tools._client = original_client

    print("Approval path:")
    print(json.dumps({"requested": requested, "approved": approved, "executed": simulated}, indent=2))
    print("\nRejection path:")
    print(json.dumps({"requested": rejected_req, "rejected": rejected, "execute_attempt": rejected_execute}, indent=2))

    assert approved["status"] == "approved"
    assert approved["approval_valid"] is True
    assert simulated["status"] == "simulated"
    assert simulated["github_request_sent"] is False
    assert rejected["status"] == "rejected"
    assert rejected_execute["status"] == "blocked"
    print("\nPASS: approval, one-time dry-run simulation, and rejection all worked without a GitHub request.")


if __name__ == "__main__":
    asyncio.run(main())
