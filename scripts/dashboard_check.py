from __future__ import annotations

from fastapi.testclient import TestClient

from contextbridge.dashboard import app


def main() -> None:
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200, health.text
    data = health.json()
    assert data["dry_run"] is True
    assert data["github_writes_enabled"] is False
    assert data["mcp_approval_available"] is False

    tools = client.get("/api/tools")
    assert tools.status_code == 200, tools.text
    names = {item["name"] for item in tools.json()}
    assert "get_evaluation_summary" in names
    assert "delete_repository" not in names

    latest = client.get("/api/evaluations/latest")
    assert latest.status_code == 200, latest.text
    assert latest.json()["available"] is True

    page = client.get("/")
    assert page.status_code == 200
    assert "ContextBridge Control Plane" in page.text

    print("Dashboard API + packaged React UI are operational.")
    print(f"Version: {data['version']}")
    print(f"Tools catalogued: {len(names)}")
    print("Safety: DRY_RUN=true, GitHub writes disabled, MCP approval unavailable")
    print("PASS: local dashboard endpoints and React control plane verified without starting a network listener.")


if __name__ == "__main__":
    main()
