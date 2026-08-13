const TOKEN_KEY = 'contextbridge_dashboard_token';
function apiHeaders() {
    const token = sessionStorage.getItem(TOKEN_KEY);
    return { 'Content-Type': 'application/json', ...(token ? { 'X-ContextBridge-Dashboard-Token': token } : {}) };
}
async function api(path, options = {}) {
    const response = await fetch(path, { ...options, headers: { ...apiHeaders(), ...(options.headers || {}) } });
    let data = null;
    try {
        data = await response.json();
    }
    catch (e) { }
    if (!response.ok) {
        const error = new Error((data === null || data === void 0 ? void 0 : data.detail) || `HTTP ${response.status}`);
        error.status = response.status;
        throw error;
    }
    return data;
}
const fmtTime = (value) => value ? new Date(value).toLocaleString() : '—';
const fmtMs = (value) => `${Math.round(Number(value || 0))} ms`;
const riskClass = (risk) => risk === 'destructive' ? 'danger' : risk === 'write' ? 'warning' : 'neutral';
const statusClass = (status) => status === 'success' || status === 'executed' || status === 'simulated' || status === 'approved' ? 'success' : status === 'pending' || status === 'confirmation_required' ? 'warning' : status === 'rejected' || status === 'error' || status === 'failed' || status === 'blocked' ? 'danger' : 'neutral';
const NAV = [['overview', 'Overview'], ['chat', 'Chat'], ['approvals', 'Approvals'], ['audit', 'Audit'], ['evaluations', 'Evaluations'], ['tools', 'Tools'], ['security', 'Security']];
function Pill(props) { return React.createElement("span", { className: `pill ${props.tone || 'neutral'}` }, props.children); }
function Metric(props) { return React.createElement("div", { className: "metric" },
    React.createElement("span", null, props.label),
    React.createElement("strong", null, props.value),
    React.createElement("small", null, props.detail)); }
function Empty(props) { return React.createElement("div", { className: "empty" },
    React.createElement("strong", null, props.title),
    React.createElement("span", null, props.body)); }
class App extends React.Component {
    constructor(props) {
        super(props);
        this.state = { tab: 'overview', health: null, metrics: null, calls: [], audit: null, actions: [], tools: [], evals: [], latestEval: null, error: '', locked: false, refreshing: false, runningEval: false, auditQuery: '', tokenInput: '', chatConfig: null, chatSessions: [], chatSessionId: null, chatMessages: [], chatEvents: [], chatInput: '', chatSending: false, chatReadOnly: true };
        this.refresh = this.refresh.bind(this);
        this.runBaseline = this.runBaseline.bind(this); this.createChat = this.createChat.bind(this); this.openChat = this.openChat.bind(this); this.sendChat = this.sendChat.bind(this);
    }
    componentDidMount() { this.refresh(); this.timer = setInterval(this.refresh, 8000); }
    componentWillUnmount() { clearInterval(this.timer); }
    async refresh() {
        this.setState({ refreshing: true, error: '' });
        try {
            const health = await api('/api/health');
            const [metrics, calls, audit, actions, tools, evals, latest, chatConfig, chatSessions] = await Promise.all([
                api('/api/metrics?hours=24'), api('/api/tool-calls?limit=120'), api('/api/audit?limit=100'),
                api('/api/actions?status=pending&limit=100'), api('/api/tools'), api('/api/evaluations?limit=20'), api('/api/evaluations/latest'), api('/api/chat/config'), api('/api/chat/sessions?limit=50')
            ]);
            this.setState({ health, metrics, calls, audit, actions, tools, evals, latestEval: (latest === null || latest === void 0 ? void 0 : latest.evaluation) || null, chatConfig, chatSessions, locked: false });
        }
        catch (err) {
            if (err.status === 401)
                this.setState({ locked: true });
            else
                this.setState({ error: err.message || String(err) });
        }
        finally {
            this.setState({ refreshing: false });
        }
    }
    async decide(action, approve) {
        const word = approve ? 'APPROVE' : 'REJECT';
        const typed = window.prompt(`${approve ? 'Approve' : 'Reject'} ${action.tool_name}\n\nType ${word} exactly to confirm.`, '');
        if (typed !== word)
            return;
        try {
            await api(`/api/actions/${encodeURIComponent(action.action_id)}/${approve ? 'approve' : 'reject'}`, { method: 'POST', body: JSON.stringify({ confirmation: word, reason: approve ? 'Approved from local dashboard' : 'Rejected from local dashboard' }) });
            await this.refresh();
        }
        catch (err) {
            this.setState({ error: err.message });
        }
    }
    async runBaseline() {
        this.setState({ runningEval: true, error: '' });
        try {
            await api('/api/evaluations/baseline', { method: 'POST', body: '{}' });
            await this.refresh();
        }
        catch (err) {
            this.setState({ error: err.message });
        }
        finally {
            this.setState({ runningEval: false });
        }
    }
    unlock() { sessionStorage.setItem(TOKEN_KEY, this.state.tokenInput); this.setState({ locked: false }, this.refresh); }
    async createChat() {
        try {
            const session = await api('/api/chat/sessions', { method: 'POST', body: JSON.stringify({ title: 'New conversation' }) });
            this.setState({ chatSessionId: session.session_id, chatMessages: [], chatEvents: [], tab: 'chat' });
            await this.refresh();
        } catch (err) { this.setState({ error: err.message || String(err) }); }
    }
    async openChat(sessionId) {
        try {
            const detail = await api(`/api/chat/sessions/${sessionId}`);
            this.setState({ chatSessionId: sessionId, chatMessages: detail.messages || [], chatEvents: detail.tool_calls || [], tab: 'chat' });
        } catch (err) { this.setState({ error: err.message || String(err) }); }
    }
    async sendChat() {
        const text = this.state.chatInput.trim(); if (!text || this.state.chatSending) return;
        let sessionId = this.state.chatSessionId;
        try {
            if (!sessionId) {
                const created = await api('/api/chat/sessions', { method: 'POST', body: JSON.stringify({ title: 'New conversation' }) });
                sessionId = created.session_id;
            }
            const optimistic = { message_id: `local_${Date.now()}`, role: 'user', content: text, created_at: new Date().toISOString() };
            this.setState({ chatSessionId: sessionId, chatInput: '', chatSending: true, chatMessages: [...this.state.chatMessages, optimistic], chatEvents: [] });
            const response = await fetch(`/api/chat/sessions/${sessionId}/stream`, { method: 'POST', headers: apiHeaders(), body: JSON.stringify({ message: text, read_only: this.state.chatReadOnly }) });
            if (!response.ok) { const d = await response.json().catch(() => ({})); throw new Error(d.detail || `HTTP ${response.status}`); }
            const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = '';
            while (true) {
                const { value, done } = await reader.read(); if (done) break; buffer += decoder.decode(value, { stream: true });
                const blocks = buffer.split('\n\n'); buffer = blocks.pop() || '';
                for (const block of blocks) {
                    const line = block.split('\n').find(x => x.startsWith('data: ')); if (!line) continue;
                    const event = JSON.parse(line.slice(6));
                    if (event.type === 'tool_start' || event.type === 'tool_end') this.setState({ chatEvents: [...this.state.chatEvents, event] });
                    if (event.type === 'final') this.setState({ chatMessages: [...this.state.chatMessages, { message_id: `assistant_${Date.now()}`, role: 'assistant', content: event.message, created_at: new Date().toISOString() }] });
                    if (event.type === 'error') this.setState({ error: event.message || 'Chat failed.' });
                }
            }
            const detail = await api(`/api/chat/sessions/${sessionId}`);
            this.setState({ chatMessages: detail.messages || [], chatEvents: detail.tool_calls || [] });
            await this.refresh();
        } catch (err) { this.setState({ error: err.message || String(err) }); }
        finally { this.setState({ chatSending: false }); }
    }
    renderChat() {
        const s = this.state;
        const cfg = s.chatConfig || {};
        const configured = cfg.configured !== false;
        const sessions = s.chatSessions.length
            ? s.chatSessions.map(x => React.createElement('button', {
                key: x.session_id,
                className: `chat-session ${s.chatSessionId === x.session_id ? 'active' : ''}`,
                onClick: () => this.openChat(x.session_id)
            }, React.createElement('strong', null, x.title), React.createElement('small', null, `${x.message_count || 0} messages · ${fmtTime(x.updated_at)}`)))
            : React.createElement(Empty, { title: 'No conversations', body: 'Create a chat to start using ContextBridge conversationally.' });
        const transcript = s.chatMessages.length
            ? s.chatMessages.map(m => React.createElement('article', { key: m.message_id, className: `chat-message ${m.role}` },
                React.createElement('span', null, m.role === 'user' ? 'You' : 'ContextBridge'),
                React.createElement('div', null, m.content)))
            : React.createElement(Empty, { title: 'Ask about your repositories', body: 'Example: “Inspect FeatureForge and explain what it does and how it is architected.”' });
        const toolEvents = s.chatEvents.length
            ? React.createElement('div', { className: 'chat-tools' },
                React.createElement('strong', null, 'Tool activity'),
                s.chatEvents.slice(-10).map((e, i) => React.createElement('div', { key: `${e.call_id || i}_${i}` },
                    React.createElement(Pill, { tone: riskClass(e.risk_level || e.risk || 'read') }, e.risk_level || e.risk || 'read'),
                    React.createElement('code', null, e.tool_name || e.name || 'tool'),
                    React.createElement('small', null, e.status || e.type))))
            : null;
        return React.createElement('div', { className: 'chat-layout' },
            React.createElement('aside', { className: 'chat-history panel' },
                React.createElement('button', { className: 'approve chat-new', onClick: this.createChat }, '+ New chat'),
                React.createElement('div', { className: 'chat-session-list' }, sessions)),
            React.createElement('section', { className: 'chat-main panel' },
                React.createElement('div', { className: 'chat-top' },
                    React.createElement('div', null,
                        React.createElement('h2', null, 'ContextBridge Assistant'),
                        React.createElement('p', null, `${cfg.provider || 'provider'} · ${cfg.model || 'model'} · MCP tool orchestration`)),
                    React.createElement('label', { className: 'readonly-toggle' },
                        React.createElement('input', { type: 'checkbox', checked: s.chatReadOnly, onChange: e => this.setState({ chatReadOnly: e.target.checked }) }),
                        ' Read-only')),
                !configured ? React.createElement('div', { className: 'chat-config-warning' }, 'Chat provider is not configured. Add the required model API key to .env and restart the dashboard.') : null,
                React.createElement('div', { className: 'chat-transcript' }, transcript,
                    s.chatSending ? React.createElement('div', { className: 'chat-thinking' }, 'ContextBridge is working…') : null),
                toolEvents,
                React.createElement('div', { className: 'chat-composer' },
                    React.createElement('textarea', {
                        value: s.chatInput,
                        onChange: e => this.setState({ chatInput: e.target.value }),
                        onKeyDown: e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); this.sendChat(); } },
                        placeholder: configured ? 'Ask ContextBridge…' : 'Configure the model provider first',
                        disabled: !configured || s.chatSending
                    }),
                    React.createElement('button', { className: 'approve', onClick: this.sendChat, disabled: !configured || s.chatSending || !s.chatInput.trim() }, s.chatSending ? 'Running…' : 'Send'))));
    }
    renderOverview() {
        var _a;
        const { metrics, calls, actions, health, latestEval } = this.state;
        const t = (metrics === null || metrics === void 0 ? void 0 : metrics.totals) || {};
        const by = (metrics === null || metrics === void 0 ? void 0 : metrics.by_tool) || [];
        const max = Math.max(1, ...by.map(x => x.calls || 0));
        const r = (latestEval === null || latestEval === void 0 ? void 0 : latestEval.report) || {};
        return React.createElement("div", { className: "fragment" },
            React.createElement("section", { className: "metrics-grid" },
                React.createElement(Metric, { label: "Tool calls", value: t.calls || 0, detail: "last 24 hours" }),
                React.createElement(Metric, { label: "Success rate", value: `${t.success_rate_pct || 0}%`, detail: `${t.failures || 0} errors · ${t.blocked || 0} blocked` }),
                React.createElement(Metric, { label: "P95 latency", value: fmtMs(t.p95_latency_ms), detail: `avg ${fmtMs(t.avg_latency_ms)}` }),
                React.createElement(Metric, { label: "Pending approvals", value: actions.length, detail: "human decisions required" }),
                React.createElement(Metric, { label: "Tool selection", value: r.tool_selection_accuracy_pct == null ? '—' : `${r.tool_selection_accuracy_pct}%`, detail: "latest recorded eval" })),
            React.createElement("div", { className: "two-col" },
                React.createElement("section", { className: "panel" },
                    React.createElement("div", { className: "panel-head" },
                        React.createElement("div", null,
                            React.createElement("h2", null, "Recent tool execution"),
                            React.createElement("p", null, "Redacted MCP activity from SQLite"))),
                    calls.length ? calls.slice(0, 8).map(x => React.createElement("div", { className: "event", key: x.request_id },
                        React.createElement("span", { className: `status-dot ${statusClass(x.status)}` }),
                        React.createElement("div", null,
                            React.createElement("strong", null, x.tool_name),
                            React.createElement("small", null, fmtTime(x.started_at))),
                        React.createElement(Pill, { tone: riskClass(x.risk_level) }, x.risk_level),
                        React.createElement("span", { className: "mono muted" }, fmtMs(x.duration_ms)))) : React.createElement(Empty, { title: "No tool calls yet", body: "MCP executions will appear here." })),
                React.createElement("section", { className: "panel" },
                    React.createElement("div", { className: "panel-head" },
                        React.createElement("div", null,
                            React.createElement("h2", null, "Runtime posture"),
                            React.createElement("p", null, "Fail-closed safety state"))),
                    React.createElement("div", { className: "posture" },
                        React.createElement("div", null,
                            React.createElement("span", null, "GitHub writes"),
                            React.createElement("strong", null, (health === null || health === void 0 ? void 0 : health.github_writes_enabled) ? 'Enabled' : 'Disabled')),
                        React.createElement("div", null,
                            React.createElement("span", null, "Dry run"),
                            React.createElement("strong", null, (health === null || health === void 0 ? void 0 : health.dry_run) ? 'Enabled' : 'Disabled')),
                        React.createElement("div", null,
                            React.createElement("span", null, "MCP can approve"),
                            React.createElement("strong", null, (health === null || health === void 0 ? void 0 : health.mcp_approval_available) ? 'Yes' : 'No')),
                        React.createElement("div", null,
                            React.createElement("span", null, "Write allowlist"),
                            React.createElement("strong", null,
                                ((_a = health === null || health === void 0 ? void 0 : health.write_repositories) === null || _a === void 0 ? void 0 : _a.length) || 0,
                                " repos")),
                        React.createElement("div", null,
                            React.createElement("span", null, "Confirmation TTL"),
                            React.createElement("strong", null,
                                (health === null || health === void 0 ? void 0 : health.confirmation_ttl_minutes) || 30,
                                " min"))))),
            React.createElement("section", { className: "panel" },
                React.createElement("div", { className: "panel-head" },
                    React.createElement("div", null,
                        React.createElement("h2", null, "Tool volume"),
                        React.createElement("p", null, "Most frequently selected semantic tools"))),
                React.createElement("div", { className: "bars" }, by.length ? by.slice(0, 12).map(x => React.createElement("div", { className: "bar-row", key: x.tool_name },
                    React.createElement("code", null, x.tool_name),
                    React.createElement("div", { className: "bar-track" },
                        React.createElement("div", { className: "bar-fill", style: { width: `${Math.max(3, (x.calls / max) * 100)}%` } })),
                    React.createElement("strong", null, x.calls))) : React.createElement(Empty, { title: "No volume yet", body: "Tool-call distribution will populate automatically." }))));
    }
    renderApprovals() { const a = this.state.actions; return React.createElement("section", { className: "panel" },
        React.createElement("div", { className: "panel-head" },
            React.createElement("div", null,
                React.createElement("h2", null, "Signed pending actions"),
                React.createElement("p", null, "Approval remains outside MCP. Exact arguments are signed and expire."))),
        a.length ? React.createElement("div", { className: "approval-grid" }, a.map(x => React.createElement("article", { className: "approval", key: x.action_id },
            React.createElement("div", { className: "approval-top" },
                React.createElement("div", null,
                    React.createElement(Pill, { tone: riskClass(x.risk_level) }, x.risk_level),
                    React.createElement("h3", null, x.tool_name)),
                React.createElement(Pill, { tone: "warning" }, "pending")),
            React.createElement("div", { className: "action-meta" },
                React.createElement("span", null,
                    "Requested ",
                    fmtTime(x.requested_at)),
                React.createElement("span", null,
                    "Expires ",
                    fmtTime(x.expires_at))),
            React.createElement("pre", null, JSON.stringify(x.arguments, null, 2)),
            React.createElement("div", { className: "fingerprint" },
                "Signature: ",
                x.signature_valid ? 'valid' : 'INVALID',
                " \u00B7 ",
                x.action_id),
            React.createElement("div", { className: "approval-actions" },
                React.createElement("button", { className: "deny", onClick: () => this.decide(x, false) }, "Reject"),
                React.createElement("button", { className: "approve", onClick: () => this.decide(x, true) }, "Approve once"))))) : React.createElement(Empty, { title: "Approval queue is clear", body: "Mutation requests will appear here before they can be executed." })); }
    renderAudit() { const { calls, audit, auditQuery } = this.state; const q = auditQuery.toLowerCase(); const rows = calls.filter(x => `${x.tool_name} ${x.status} ${x.error_type || ''}`.toLowerCase().includes(q)); return React.createElement("div", { className: "fragment" },
        React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Execution log"),
                    React.createElement("p", null, "Arguments are stored with secret-like fields redacted")),
                React.createElement("input", { className: "search", value: auditQuery, onChange: e => this.setState({ auditQuery: e.target.value }), placeholder: "Filter tools or status" })),
            React.createElement("div", { className: "table-wrap" },
                React.createElement("table", null,
                    React.createElement("thead", null,
                        React.createElement("tr", null,
                            React.createElement("th", null, "Time"),
                            React.createElement("th", null, "Tool"),
                            React.createElement("th", null, "Risk"),
                            React.createElement("th", null, "Status"),
                            React.createElement("th", null, "Latency"),
                            React.createElement("th", null, "Error"))),
                    React.createElement("tbody", null, rows.map(x => React.createElement("tr", { key: x.request_id },
                        React.createElement("td", null, fmtTime(x.started_at)),
                        React.createElement("td", null,
                            React.createElement("code", null, x.tool_name)),
                        React.createElement("td", null,
                            React.createElement(Pill, { tone: riskClass(x.risk_level) }, x.risk_level)),
                        React.createElement("td", null,
                            React.createElement(Pill, { tone: statusClass(x.status) }, x.status)),
                        React.createElement("td", null, fmtMs(x.duration_ms)),
                        React.createElement("td", null, x.error_type || '—'))))))),
        React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Audit summary"),
                    React.createElement("p", null, "Append-only event stream"))),
            React.createElement("div", { className: "audit-stats" },
                React.createElement(Metric, { label: "Events", value: (audit === null || audit === void 0 ? void 0 : audit.total_events) || 0, detail: "all returned events" }),
                React.createElement(Metric, { label: "System events", value: (audit === null || audit === void 0 ? void 0 : audit.system_events_all_time) || 0, detail: "all time" }),
                React.createElement(Metric, { label: "Pending", value: (audit === null || audit === void 0 ? void 0 : audit.pending_actions) || 0, detail: "signed actions" })))); }
    renderEvaluations() { var _a; const { evals, latestEval, runningEval } = this.state; const r = (latestEval === null || latestEval === void 0 ? void 0 : latestEval.report) || {}; return React.createElement("div", { className: "fragment" },
        React.createElement("section", { className: "eval-hero panel" },
            React.createElement("div", null,
                React.createElement("span", { className: "eyebrow" }, "100-CASE BENCHMARK"),
                React.createElement("h2", null, "Tool-selection evaluation"),
                React.createElement("p", null, "The bundled baseline is a deterministic harness smoke test. Export predictions from the actual MCP host/model to measure real model behavior.")),
            React.createElement("button", { className: "approve", onClick: this.runBaseline, disabled: runningEval }, runningEval ? 'Running…' : 'Run offline baseline')),
        React.createElement("section", { className: "metrics-grid four" },
            React.createElement(Metric, { label: "Selection accuracy", value: r.tool_selection_accuracy_pct == null ? '—' : `${r.tool_selection_accuracy_pct}%`, detail: "latest run" }),
            React.createElement(Metric, { label: "Parameter accuracy", value: r.parameter_accuracy_pct == null ? '—' : `${r.parameter_accuracy_pct}%`, detail: `${r.parameter_cases || 0} argument-bearing cases` }),
            React.createElement(Metric, { label: "Risk accuracy", value: r.risk_accuracy_pct == null ? '—' : `${r.risk_accuracy_pct}%`, detail: "read / write / destructive" }),
            React.createElement(Metric, { label: "Mutation classification", value: r.mutation_classification_accuracy_pct == null ? '—' : `${r.mutation_classification_accuracy_pct}%`, detail: "confirmation expectation" })),
        React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Evaluation history"),
                    React.createElement("p", null, "Persisted benchmark runs"))),
            evals.length ? React.createElement("div", { className: "table-wrap" },
                React.createElement("table", null,
                    React.createElement("thead", null,
                        React.createElement("tr", null,
                            React.createElement("th", null, "Run"),
                            React.createElement("th", null, "Mode"),
                            React.createElement("th", null, "Cases"),
                            React.createElement("th", null, "Tool accuracy"),
                            React.createElement("th", null, "Parameter accuracy"),
                            React.createElement("th", null, "Created"))),
                    React.createElement("tbody", null, evals.map(x => React.createElement("tr", { key: x.run_id },
                        React.createElement("td", null,
                            React.createElement("code", null,
                                x.run_id.slice(0, 16),
                                "\u2026")),
                        React.createElement("td", null,
                            React.createElement(Pill, { tone: x.mode === 'baseline' ? 'neutral' : 'success' }, x.mode)),
                        React.createElement("td", null, x.case_count),
                        React.createElement("td", null,
                            x.tool_selection_accuracy,
                            "%"),
                        React.createElement("td", null, x.parameter_accuracy == null ? '—' : `${x.parameter_accuracy}%`),
                        React.createElement("td", null, fmtTime(x.created_at))))))) : React.createElement(Empty, { title: "No evaluations recorded", body: "Run the offline baseline or score predictions exported from your MCP host." })),
        ((_a = r.top_confusions) === null || _a === void 0 ? void 0 : _a.length) ? React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Top confusions"),
                    React.createElement("p", null, "Most frequent wrong tool selections"))),
            React.createElement("div", { className: "confusions" }, r.top_confusions.map((x, i) => React.createElement("div", { key: i },
                React.createElement("code", null, x.expected),
                React.createElement("span", null, "\u2192"),
                React.createElement("code", null, x.actual),
                React.createElement("strong", null, x.count))))) : null); }
    renderTools() { const t = this.state.tools; return React.createElement("section", { className: "panel" },
        React.createElement("div", { className: "panel-head" },
            React.createElement("div", null,
                React.createElement("h2", null, "Semantic tool catalog"),
                React.createElement("p", null, "Purpose-built operations rather than an arbitrary raw API proxy")),
            React.createElement("strong", null,
                t.length,
                " tools")),
        React.createElement("div", { className: "tool-grid" }, t.map(x => React.createElement("article", { className: "tool", key: x.name },
            React.createElement("div", null,
                React.createElement("code", null, x.name),
                React.createElement(Pill, { tone: riskClass(x.risk) }, x.risk)),
            React.createElement("p", null, x.description),
            React.createElement("small", null, x.human_confirmation ? 'Human approval required' : 'Immediate read-only execution'))))); }
    renderSecurity() { var _a, _b; const h = this.state.health; return React.createElement("div", { className: "two-col" },
        React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Safety invariants"),
                    React.createElement("p", null, "Current v0.9 posture"))),
            React.createElement("ul", { className: "checks" },
                React.createElement("li", null, "\u2713 Approval/rejection is not exposed as an MCP tool"),
                React.createElement("li", null, "\u2713 Pending actions are HMAC signed"),
                React.createElement("li", null, "\u2713 Approved actions are one-time claims"),
                React.createElement("li", null, "\u2713 Audit records are append-only"),
                React.createElement("li", null, "\u2713 Dashboard defaults to 127.0.0.1 only"),
                React.createElement("li", null, "\u2713 Non-loopback dashboard binding requires a token"),
                React.createElement("li", null, "\u2713 Repository/code/admin mutation capabilities remain absent"))),
        React.createElement("section", { className: "panel" },
            React.createElement("div", { className: "panel-head" },
                React.createElement("div", null,
                    React.createElement("h2", null, "Current configuration"),
                    React.createElement("p", null, "Secrets are never returned"))),
            React.createElement("div", { className: "posture" },
                React.createElement("div", null,
                    React.createElement("span", null, "Environment"),
                    React.createElement("strong", null, (h === null || h === void 0 ? void 0 : h.environment) || '—')),
                React.createElement("div", null,
                    React.createElement("span", null, "Dry run"),
                    React.createElement("strong", null, String(h === null || h === void 0 ? void 0 : h.dry_run))),
                React.createElement("div", null,
                    React.createElement("span", null, "GitHub writes"),
                    React.createElement("strong", null, String(h === null || h === void 0 ? void 0 : h.github_writes_enabled))),
                React.createElement("div", null,
                    React.createElement("span", null, "Writable repositories"),
                    React.createElement("strong", null, ((_a = h === null || h === void 0 ? void 0 : h.write_repositories) === null || _a === void 0 ? void 0 : _a.length) || 0)),
                React.createElement("div", null,
                    React.createElement("span", null, "Database schema"),
                    React.createElement("strong", null,
                        "v",
                        ((_b = h === null || h === void 0 ? void 0 : h.database) === null || _b === void 0 ? void 0 : _b.schema_version) || '—'))))); }
    renderPage() { switch (this.state.tab) {
        case 'overview': return this.renderOverview();
        case 'chat': return this.renderChat();
        case 'approvals': return this.renderApprovals();
        case 'audit': return this.renderAudit();
        case 'evaluations': return this.renderEvaluations();
        case 'tools': return this.renderTools();
        case 'security': return this.renderSecurity();
        default: return null;
    } }
    render() { var _a, _b, _c, _d; const s = this.state; const label = (NAV.find(x => x[0] === s.tab) || ['', 'ContextBridge'])[1]; return React.createElement("div", { className: "shell" },
        React.createElement("aside", { className: "sidebar" },
            React.createElement("div", { className: "brand" },
                React.createElement("div", { className: "brand-mark" }, "CB"),
                React.createElement("div", null,
                    React.createElement("strong", null, "ContextBridge"),
                    React.createElement("span", null, "Control Plane"))),
            React.createElement("nav", null, NAV.map(([id, name]) => React.createElement("button", { key: id, className: s.tab === id ? 'active' : '', onClick: () => this.setState({ tab: id }) },
                React.createElement("span", { className: "nav-dot" }),
                React.createElement("span", null, name),
                id === 'approvals' && s.actions.length > 0 ? React.createElement("b", null, s.actions.length) : null))),
            React.createElement("div", { className: "side-status" },
                React.createElement("div", null,
                    React.createElement("span", { className: "live-dot" }),
                    "local"),
                React.createElement("small", null,
                    "v",
                    ((_a = s.health) === null || _a === void 0 ? void 0 : _a.version) || '0.9.0'))),
        React.createElement("main", { className: "main" },
            React.createElement("header", null,
                React.createElement("div", null,
                    React.createElement("span", { className: "eyebrow" }, "AI INFRASTRUCTURE"),
                    React.createElement("h1", null, label)),
                React.createElement("div", { className: "header-actions" },
                    React.createElement(Pill, { tone: ((_b = s.health) === null || _b === void 0 ? void 0 : _b.dry_run) ? 'success' : 'warning' }, ((_c = s.health) === null || _c === void 0 ? void 0 : _c.dry_run) ? 'DRY RUN' : 'LIVE MODE'),
                    React.createElement("button", { className: "refresh", onClick: this.refresh, disabled: s.refreshing }, s.refreshing ? 'Refreshing…' : 'Refresh'))),
            s.error ? React.createElement("div", { className: "error-banner" }, s.error) : null,
            this.renderPage(),
            React.createElement("footer", null,
                "ContextBridge v",
                ((_d = s.health) === null || _d === void 0 ? void 0 : _d.version) || '0.9.0',
                " \u00B7 MCP human-control plane \u00B7 localhost by default")),
        s.locked ? React.createElement("div", { className: "overlay" },
            React.createElement("div", { className: "unlock" },
                React.createElement("div", { className: "brand-mark" }, "CB"),
                React.createElement("h2", null, "Dashboard token required"),
                React.createElement("p", null, "This dashboard instance is protected. The token stays in sessionStorage for this tab."),
                React.createElement("input", { type: "password", value: s.tokenInput, onChange: e => this.setState({ tokenInput: e.target.value }), onKeyDown: e => { if (e.key === 'Enter')
                        this.unlock(); }, placeholder: "CONTEXTBRIDGE_DASHBOARD_TOKEN" }),
                React.createElement("button", { className: "approve", onClick: () => this.unlock() }, "Unlock"))) : null); }
}
ReactDOM.render(React.createElement(App, null), document.getElementById('root'));
