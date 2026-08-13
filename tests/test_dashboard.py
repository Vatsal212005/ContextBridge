from __future__ import annotations

from fastapi.testclient import TestClient

from contextbridge.dashboard import app


def test_dashboard_health_is_local_safe() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "0.9.1"
    assert data["dry_run"] is True
    assert data["github_writes_enabled"] is False
    assert data["mcp_approval_available"] is False


def test_dashboard_tool_catalog_has_evaluation_tool() -> None:
    client = TestClient(app)
    response = client.get("/api/tools")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "get_evaluation_summary" in names
    assert "delete_repository" not in names


def test_react_dashboard_static_page_is_packaged() -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "ContextBridge Control Plane" in response.text


def test_prebuilt_react_bundle_matches_class_component_build() -> None:
    from contextbridge.dashboard import STATIC_DIR
    app_js = (STATIC_DIR / "app.js").read_text(encoding="utf-8")
    react_js = (STATIC_DIR / "react.production.min.js").read_text(encoding="utf-8")
    assert "ReactDOM.render" in app_js
    assert "React.Fragment" not in app_js
    assert "useState" not in app_js
    assert "React" in react_js
