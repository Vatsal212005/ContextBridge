# Five-minute portfolio demo

1. Run `scripts/github_read_check.py` to show real authenticated repository access.
2. Open MCP Inspector and ask for `list_repositories`, `search_issues`, and `get_file_contents`.
3. Request `create_issue` and show that ContextBridge returns `confirmation_required` instead of
   touching GitHub.
4. Open the dashboard and show the signed pending action, audit record, latency metrics, and safety
   posture. Approve the action locally; execution remains a dry-run simulation in v0.8.
5. Open Evaluations and run the 100-case offline baseline. Explain that the bundled router only
   validates the harness; real model scores come from exported MCP-host predictions.

Interview discussion points: semantic tool design, least privilege, rate-limit handling, retry
semantics, exact-action human confirmation, replay protection, auditability, provider-agnostic
evaluation, and why approval is intentionally outside the MCP surface.
