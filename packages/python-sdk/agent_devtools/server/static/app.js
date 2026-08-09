const API = "/api";

const state = {
  runs: [],
  selectedRunId: null,
  activeTab: "replay",
  diffA: null,
  diffB: null,
};

async function api(path, options) {
  const res = await fetch(API + path, options);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function truncate(str, n = 240) {
  const s = String(str ?? "");
  return s.length > n ? s.slice(0, n) + "\u2026" : s;
}

function jsonInline(v) {
  if (v === undefined) return "";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

function jsonPretty(value) {
  return escapeHtml(JSON.stringify(value, null, 2));
}

function fmtTime(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString([], { hour12: false }) + "." + String(d.getMilliseconds()).padStart(3, "0");
}

function relTime(ts) {
  if (!ts) return "";
  const diff = Date.now() / 1000 - ts;
  if (diff < 5) return "just now";
  if (diff < 60) return `${Math.floor(diff)}s ago`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  return `${Math.floor(diff / 3600)}h ago`;
}

function emptyHint(text) {
  return `<div class="empty-hint">${text}</div>`;
}

function emptyStateHtml(title, body) {
  return `<div class="empty-state"><div class="empty-title">${title}</div><div class="empty-body">${body}</div></div>`;
}

function statusClass(status) {
  if (status === "ok") return "ok";
  if (status === "error") return "error";
  return "running";
}

/* -------------------------------------------------------------------- */
/* Sidebar: run list                                                      */
/* -------------------------------------------------------------------- */

function renderRunList() {
  const el = document.getElementById("run-list");
  document.getElementById("run-count").textContent = state.runs.length;
  if (!state.runs.length) {
    el.innerHTML = emptyHint("Waiting for a run\u2026");
    return;
  }
  el.innerHTML = state.runs
    .map(
      (r) => `
    <div class="run-item ${r.id === state.selectedRunId ? "selected" : ""}" data-run="${escapeHtml(r.id)}">
      <div class="run-item-top">
        <span class="run-status-dot ${statusClass(r.status)}"></span>
        <span class="run-item-name">${escapeHtml(r.id)}</span>
      </div>
      <div class="run-item-meta">${escapeHtml(r.agent_name)} &middot; ${r.event_count} events &middot; ${relTime(r.started_at)}</div>
    </div>`
    )
    .join("");
  el.querySelectorAll(".run-item").forEach((node) => {
    node.addEventListener("click", () => selectRun(node.dataset.run));
  });
}

function selectRun(runId) {
  state.selectedRunId = runId;
  renderRunList();
  renderActiveTab();
}

/* -------------------------------------------------------------------- */
/* Tab strip                                                              */
/* -------------------------------------------------------------------- */

document.getElementById("tabstrip").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (!btn) return;
  document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
  btn.classList.add("active");
  state.activeTab = btn.dataset.tab;
  history.replaceState(null, "", "#" + state.activeTab);
  renderActiveTab();
});

async function renderActiveTab() {
  const content = document.getElementById("content");
  if (state.activeTab !== "diff" && !state.selectedRunId) {
    content.innerHTML = emptyStateHtml(
      "No run selected",
      "Instrument a run with the Python SDK, then pick it up on the left."
    );
    return;
  }
  try {
    if (state.activeTab === "replay") return await renderReplay();
    if (state.activeTab === "graph") return await renderGraph();
    if (state.activeTab === "prompt") return await renderPrompt();
    if (state.activeTab === "context") return await renderContext();
    if (state.activeTab === "retrieval") return await renderRetrieval();
    if (state.activeTab === "memory") return await renderMemory();
    if (state.activeTab === "tools") return await renderTools();
    if (state.activeTab === "diff") return await renderDiff();
  } catch (err) {
    content.innerHTML = emptyStateHtml("Couldn't load this tab", escapeHtml(err.message));
  }
}

/* -------------------------------------------------------------------- */
/* Event badges + generic payload summaries (used by Replay & Memory)     */
/* -------------------------------------------------------------------- */

const BADGE_MAP = {
  "user.input": ["input", "input"],
  "retrieval.query": ["retrieval", "retrieval query"],
  "retrieval.result": ["retrieval", "retrieval result"],
  "context.block": ["context", "context"],
  "prompt.assembled": ["prompt", "prompt"],
  "tool.call": ["tool", "tool call"],
  "tool.result": ["tool", "tool result"],
  "memory.read": ["memory", "memory read"],
  "memory.write": ["memory", "memory write"],
  "memory.update": ["memory", "memory update"],
  "memory.delete": ["memory", "memory delete"],
  "model.response": ["output", "output"],
  "state.snapshot": ["memory", "state snapshot"],
  "assertion.passed": ["assert-pass", "assertion pass"],
  "assertion.failed": ["assert-fail", "assertion fail"],
};

function badgeFor(type) {
  const [cls, label] = BADGE_MAP[type] || ["tool", type];
  return `<span class="badge b-${cls}">${escapeHtml(label)}</span>`;
}

function renderPayloadSummary(type, p) {
  switch (type) {
    case "user.input":
      return `<div>${escapeHtml(truncate(p.message, 500))}</div>`;
    case "retrieval.query":
      return `<div><span class="k">query:</span> ${escapeHtml(p.query)}</div>`;
    case "retrieval.result":
      return (p.results || [])
        .map(
          (r) =>
            `<div>#${r.rank ?? "-"} <span class="s">${escapeHtml(r.id || "")}</span> (${escapeHtml(
              r.source || ""
            )}, score ${r.score ?? "-"})${r.selected ? " \u2713 selected" : ""}<br><span class="k">${escapeHtml(
              truncate(r.content, 160)
            )}</span></div>`
        )
        .join("");
    case "context.block":
      return `<div><span class="k">source:</span> ${escapeHtml(p.source)}${
        p.key ? ` &middot; <span class="k">key:</span> ${escapeHtml(p.key)}` : ""
      }</div><div>${escapeHtml(truncate(p.content, 300))}</div>`;
    case "prompt.assembled":
      return `<div><span class="k">system:</span> ${escapeHtml(truncate(p.system, 160))}</div><div><span class="k">messages:</span> ${
        (p.messages || []).length
      }</div>`;
    case "tool.call":
      return `<div><span class="k">${escapeHtml(p.name)}(</span>${escapeHtml(jsonInline(p.args))}<span class="k">)</span></div>`;
    case "tool.result":
      return p.error
        ? `<div style="color:var(--bad)">error: ${escapeHtml(p.error)}</div>`
        : `<div>${escapeHtml(jsonInline(p.result))}</div>`;
    case "memory.read":
    case "memory.write":
      return `<div><span class="k">${escapeHtml(p.key)}</span> = ${escapeHtml(jsonInline(p.value))}</div>`;
    case "memory.update":
      return `<div><span class="k">${escapeHtml(p.key)}</span>: ${escapeHtml(jsonInline(p.old_value))} &rarr; ${escapeHtml(
        jsonInline(p.new_value)
      )}</div>`;
    case "memory.delete":
      return `<div>deleted <span class="k">${escapeHtml(p.key)}</span></div>`;
    case "model.response":
      return `<div>${escapeHtml(truncate(p.response, 800))}</div>`;
    case "assertion.passed":
    case "assertion.failed":
      return `<div>${escapeHtml(p.name)}${p.details ? " &mdash; " + escapeHtml(p.details) : ""}</div>`;
    default:
      return `<pre class="raw">${jsonPretty(p)}</pre>`;
  }
}

function renderTimelineItem(e) {
  return `
    <div class="tl-item">
      <div class="tl-head">
        ${badgeFor(e.type)}
        <span class="tl-time">${fmtTime(e.ts)}</span>
      </div>
      <div class="card kv">${renderPayloadSummary(e.type, e.payload)}</div>
    </div>`;
}

/* -------------------------------------------------------------------- */
/* Replay tab                                                             */
/* -------------------------------------------------------------------- */

async function renderReplay() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}`);
  const items = data.events.map(renderTimelineItem).join("");
  content.innerHTML = `
    <div class="panel-title">Run ${escapeHtml(data.run.id)} &middot; ${escapeHtml(data.run.agent_name)} &middot; ${escapeHtml(
    data.run.status
  )}</div>
    <div class="timeline">${items || emptyHint("No events recorded on this run yet.")}</div>`;
}

/* -------------------------------------------------------------------- */
/* Graph tab -- visual flow of the current run                            */
/* -------------------------------------------------------------------- */

const GRAPH_STAGES = [
  { id: "input", label: "User Input", icon: "✉", tab: "replay", types: ["user.input"] },
  { id: "retrieval", label: "Retrieval", icon: "⌕", tab: "retrieval", types: ["retrieval.query", "retrieval.result"] },
  { id: "memory", label: "Memory", icon: "▤", tab: "memory", types: ["memory.read", "memory.write", "memory.update", "memory.delete", "state.snapshot"] },
  { id: "prompt", label: "Prompt", icon: "❯", tab: "prompt", types: ["prompt.assembled", "context.block"] },
  { id: "llm", label: "LLM / Output", icon: "◈", tab: "replay", types: ["model.response"] },
  { id: "tool", label: "Tool Call", icon: "⚙", tab: "tools", types: ["tool.call", "tool.result"] },
  { id: "final", label: "Final Answer", icon: "✓", tab: "replay", types: [] },
];

function graphNodeHtml(stage, events, isLast) {
  const count = events.length;
  const hasEvents = count > 0;
  const cls = hasEvents ? "active" : "inactive";
  const badge = hasEvents ? `<span class="graph-count">${count}</span>` : "";
  const arrow = isLast ? "" : `<div class="graph-arrow">&#8594;</div>`;
  return `
    <div class="graph-node-wrap">
      <div class="graph-node ${cls}" data-tab="${stage.tab}" data-stage="${stage.id}" title="Open ${stage.label} tab">
        <div class="graph-node-icon">${stage.icon}</div>
        <div class="graph-node-label">${escapeHtml(stage.label)}</div>
        ${badge}
      </div>
      ${arrow}
    </div>`;
}

function graphDetailHtml(stage, events) {
  if (!events.length) {
    return `<div class="graph-detail-empty">No ${escapeHtml(stage.label.toLowerCase())} events recorded in this run.</div>`;
  }
  return events.map(renderTimelineItem).join("");
}

async function renderGraph() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}`);
  const events = data.events;

  const stageEvents = {};
  GRAPH_STAGES.forEach((s) => (stageEvents[s.id] = []));
  events.forEach((e) => {
    for (const s of GRAPH_STAGES) {
      if (s.types.includes(e.type)) {
        stageEvents[s.id].push(e);
        break;
      }
    }
  });

  // The last model.response is the final answer
  const modelResponses = events.filter((e) => e.type === "model.response");
  if (modelResponses.length) {
    stageEvents.final.push(modelResponses[modelResponses.length - 1]);
  }

  const nodes = GRAPH_STAGES.map((s, i) => graphNodeHtml(s, stageEvents[s.id], i === GRAPH_STAGES.length - 1)).join("");

  content.innerHTML = `
    <div class="panel-title">Run flow &middot; ${escapeHtml(data.run.id)} &middot; ${escapeHtml(data.run.agent_name)} &middot; ${escapeHtml(data.run.status)}</div>
    <div class="graph-flow">${nodes}</div>
    <div class="graph-detail" id="graph-detail">
      <div class="panel-title">Stage details</div>
      <div class="graph-detail-body" id="graph-detail-body">
        <div class="empty-hint">Click a node above to inspect its events.</div>
      </div>
    </div>`;

  content.querySelectorAll(".graph-node").forEach((node) => {
    node.addEventListener("click", () => {
      const stageId = node.dataset.stage;
      const stage = GRAPH_STAGES.find((s) => s.id === stageId);
      if (!stage) return;

      // Highlight the selected node
      content.querySelectorAll(".graph-node").forEach((n) => n.classList.remove("selected"));
      node.classList.add("selected");

      // Show details for this stage
      const body = document.getElementById("graph-detail-body");
      const stageEvts = stageEvents[stageId];
      body.innerHTML = graphDetailHtml(stage, stageEvts);

      // Also allow jumping to the corresponding tab
      const jumpBtn = document.createElement("button");
      jumpBtn.className = "graph-jump-btn";
      jumpBtn.textContent = `Open ${stage.label} tab \u2192`;
      jumpBtn.addEventListener("click", () => {
        const tabBtn = document.querySelector(`.tab[data-tab="${stage.tab}"]`);
        if (tabBtn) tabBtn.click();
      });
      body.prepend(jumpBtn);
    });
  });
}

/* -------------------------------------------------------------------- */
/* Prompt tab                                                             */
/* -------------------------------------------------------------------- */

async function renderPrompt() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}/prompt`);
  if (!data.prompt) {
    content.innerHTML = emptyStateHtml(
      "No prompt recorded",
      "Call run.prompt(system=..., messages=..., context=...) inside this run to see the final assembled model input here."
    );
    return;
  }
  const p = data.prompt.payload;
  let html = `<div class="panel-title">Final assembled prompt</div>`;
  if (p.system) {
    html += `<div class="msg role-system"><div class="msg-role">system</div><div>${escapeHtml(p.system)}</div></div>`;
  }
  (p.messages || []).forEach((m) => {
    const roleClass = ["system", "user", "assistant"].includes(m.role) ? m.role : "user";
    html += `<div class="msg role-${roleClass}"><div class="msg-role">${escapeHtml(
      m.role || "message"
    )}</div><div>${escapeHtml(typeof m.content === "string" ? m.content : JSON.stringify(m.content))}</div></div>`;
  });
  if (p.context && p.context.length) {
    html += `<div class="panel-title">Context references included</div><div class="card kv">${p.context
      .map((c) => `<span class="badge b-context">${escapeHtml(c)}</span>`)
      .join(" ")}</div>`;
  }
  content.innerHTML = html;
}

/* -------------------------------------------------------------------- */
/* Context tab                                                            */
/* -------------------------------------------------------------------- */

async function renderContext() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}/context`);
  if (!data.blocks.length) {
    content.innerHTML = emptyStateHtml(
      "No context blocks recorded",
      "Call run.context_block(source=..., content=..., key=...) to record what was injected, in what order, and where it came from."
    );
    return;
  }
  const items = data.blocks
    .map((e, i) => {
      const p = e.payload;
      return `<div class="card">
        <div class="ctx-block">
          <div class="ctx-order">${p.order ?? i}</div>
          <div class="ctx-body">
            <div class="ctx-source-row">
              <span class="badge b-context">${escapeHtml(p.source)}</span>
              ${p.key ? `<span class="ctx-key">${escapeHtml(p.key)}</span>` : ""}
            </div>
            <div class="kv">${escapeHtml(p.content)}</div>
          </div>
        </div>
      </div>`;
    })
    .join("");
  content.innerHTML = `<div class="panel-title">Context provenance &middot; injection order</div>${items}`;
}

/* -------------------------------------------------------------------- */
/* Retrieval tab                                                          */
/* -------------------------------------------------------------------- */

function fmtScore(v) {
  if (v === null || v === undefined) return "\u2014";
  return escapeHtml(v);
}

function renderRetrievalMeta(exp) {
  const rows = [];
  if (exp.rewritten_query) {
    rows.push(`<div class="retr-meta-row"><span class="k">rewritten query:</span> ${escapeHtml(exp.rewritten_query)}</div>`);
  }
  if (exp.filters && Object.keys(exp.filters).length) {
    rows.push(`<div class="retr-meta-row"><span class="k">filters:</span> ${escapeHtml(JSON.stringify(exp.filters))}</div>`);
  }
  if (exp.embedding_model) {
    rows.push(`<div class="retr-meta-row"><span class="k">embedding model:</span> ${escapeHtml(exp.embedding_model)}</div>`);
  }
  if (exp.threshold !== undefined && exp.threshold !== null) {
    rows.push(`<div class="retr-meta-row"><span class="k">threshold:</span> ${escapeHtml(exp.threshold)}</div>`);
  }
  if (exp.rerank_threshold !== undefined && exp.rerank_threshold !== null) {
    rows.push(`<div class="retr-meta-row"><span class="k">rerank threshold:</span> ${escapeHtml(exp.rerank_threshold)}</div>`);
  }
  return rows.join("");
}

function renderRetrievalResultRow(r) {
  const selected = r.selected === true;
  const rejected = r.selected === false;
  const stateBadge = selected
    ? `<span class="retr-state selected">\u2713 selected</span>`
    : rejected
    ? `<span class="retr-state rejected">\u2717 rejected</span>`
    : `<span class="retr-state unknown">\u2014</span>`;
  return `
    <tr class="${selected ? "selected" : ""}">
      <td><span class="rank-pill">#${r.rank ?? "-"}</span></td>
      <td class="mono">${escapeHtml(r.id || "")}</td>
      <td>${escapeHtml(r.source || "")}</td>
      <td class="mono">${fmtScore(r.score)}</td>
      <td class="mono">${fmtScore(r.rerank_score)}</td>
      <td class="mono">${fmtScore(r.threshold)}</td>
      <td>${stateBadge}</td>
      <td class="retr-reason">${escapeHtml(r.reason || "")}</td>
    </tr>`;
}

async function renderRetrieval() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}/retrieval/explain`);
  const explanations = data.explanations || [];
  if (!explanations.length) {
    content.innerHTML = emptyStateHtml(
      "No retrieval recorded",
      "Call run.retrieval(query, results) to see queries, scores, ranks and which candidates were selected."
    );
    return;
  }
  let html = `<div class="panel-title">Retrieval</div>`;
  explanations.forEach((exp) => {
    const rows = [...(exp.results || [])].sort((a, b) => (a.rank ?? 0) - (b.rank ?? 0));
    html += `
      <div class="card">
        <div class="retr-query-row">
          <span class="k">query:</span> ${escapeHtml(exp.query)}
        </div>
        ${renderRetrievalMeta(exp)}
        <div class="scroll-x">
        <table class="rt retr-table">
          <thead><tr><th>Rank</th><th>Id</th><th>Source</th><th>Score</th><th>Rerank</th><th>Threshold</th><th>State</th><th>Reason</th></tr></thead>
          <tbody>
            ${rows.map(renderRetrievalResultRow).join("")}
          </tbody>
        </table>
        </div>
        ${exp.summary ? `<div class="retr-summary">${escapeHtml(exp.summary)}</div>` : ""}
      </div>`;
  });
  content.innerHTML = html;
}

/* -------------------------------------------------------------------- */
/* Memory tab                                                             */
/* -------------------------------------------------------------------- */

async function renderMemory() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}/memory`);
  if (!data.events.length) {
    content.innerHTML = emptyStateHtml(
      "No memory events recorded",
      "Call run.memory_write / memory_read / memory_update / memory_delete to see the memory lifecycle here."
    );
    return;
  }
  const items = data.events.map(renderTimelineItem).join("");
  content.innerHTML = `<div class="panel-title">Memory lifecycle</div><div class="timeline">${items}</div>`;
}

/* -------------------------------------------------------------------- */
/* Tools tab                                                              */
/* -------------------------------------------------------------------- */

async function renderTools() {
  const content = document.getElementById("content");
  const data = await api(`/runs/${encodeURIComponent(state.selectedRunId)}/tools`);
  if (!data.events.length) {
    content.innerHTML = emptyStateHtml(
      "No tool calls recorded",
      "Call run.tool_call(name=..., args=..., result=...) to see calls, arguments, outputs and errors here."
    );
    return;
  }
  const items = data.events.map(renderTimelineItem).join("");
  content.innerHTML = `<div class="panel-title">Tool calls</div><div class="timeline">${items}</div>`;
}

/* -------------------------------------------------------------------- */
/* Diff tab -- the signature feature                                       */
/* -------------------------------------------------------------------- */

function confidenceBadge(conf) {
  // conf is 0.0 - 1.0
  const pct = Math.round((conf || 0) * 100);
  const cls = pct >= 80 ? "conf-high" : pct >= 50 ? "conf-mid" : "conf-low";
  return `<span class="conf-badge ${cls}" title="Heuristic confidence">${pct}%</span>`;
}

function renderTokenDiff(tokenDiff) {
  if (!tokenDiff || !tokenDiff.ops || !tokenDiff.ops.length) return "";
  const ops = tokenDiff.ops
    .map((op) => {
      if (op.added && !op.removed) {
        return `<span class="tok-add">${escapeHtml(op.added)}</span>`;
      }
      if (op.removed && !op.added) {
        return `<span class="tok-del">${escapeHtml(op.removed)}</span>`;
      }
      return `<span class="tok-replace">${escapeHtml(op.removed)} &rarr; ${escapeHtml(op.added)}</span>`;
    })
    .join(" ");
  return `<div class="token-diff">
    <div class="token-diff-title">Token-level prompt diff (${tokenDiff.removed_count} removed, ${tokenDiff.added_count} added spans)</div>
    <div class="token-diff-body">${ops}</div>
  </div>`;
}

async function renderDiff() {
  const content = document.getElementById("content");

  if (state.runs.length < 2) {
    content.innerHTML = emptyStateHtml(
      "Need two runs to compare",
      "Instrument a good run and a bad run of the same agent, then come back here to see exactly what changed."
    );
    return;
  }

  if (!state.diffA) state.diffA = state.runs[state.runs.length - 1].id;
  if (!state.diffB) state.diffB = state.runs[0].id;

  const optionsFor = (selectedId) =>
    state.runs
      .map((r) => `<option value="${escapeHtml(r.id)}" ${r.id === selectedId ? "selected" : ""}>${escapeHtml(r.id)}</option>`)
      .join("");

  // Multi-select for the "bad" side when comparing against multiple runs.
  const badOptions = state.runs
    .filter((r) => r.id !== state.diffA)
    .map((r) => `<option value="${escapeHtml(r.id)}" ${(state.diffB || "").split(",").includes(r.id) ? "selected" : ""}>${escapeHtml(r.id)}</option>`)
    .join("");

  content.innerHTML = `
    <div class="panel-title">Behavior diff</div>
    <div class="diff-picker">
      <span class="diff-col-head good" style="border:none;padding:0;">good</span>
      <select id="diff-a">${optionsFor(state.diffA)}</select>
      <span class="diff-arrow">vs</span>
      <span class="diff-col-head bad" style="border:none;padding:0;">bad</span>
      <select id="diff-b" multiple size="4">${badOptions}</select>
      <button class="diff-run-btn" id="diff-run-btn">Compare</button>
    </div>
    <div class="diff-picker-hint">Hold ⌘/Ctrl to select multiple bad runs for a multi-run comparison.</div>
    <div id="diff-result"></div>`;

  document.getElementById("diff-run-btn").addEventListener("click", async () => {
    state.diffA = document.getElementById("diff-a").value;
    const sel = Array.from(document.getElementById("diff-b").selectedOptions).map((o) => o.value);
    state.diffB = sel.join(",");
    await runDiffCompare();
  });

  if (state.diffA && state.diffB) {
    await runDiffCompare();
  }
}

async function runDiffCompare() {
  const resultEl = document.getElementById("diff-result");
  if (!resultEl) return;
  if (!state.diffA || !state.diffB) return;

  const badList = state.diffB.split(",").filter(Boolean);
  if (!badList.length) {
    resultEl.innerHTML = emptyHint("Pick at least one bad run to compare.");
    return;
  }
  if (badList.length === 1 && badList[0] === state.diffA) {
    resultEl.innerHTML = emptyHint("Pick different runs to compare.");
    return;
  }

  resultEl.innerHTML = emptyHint("Comparing\u2026");
  try {
    if (badList.length === 1) {
      const data = await api(`/diff?a=${encodeURIComponent(state.diffA)}&b=${encodeURIComponent(badList[0])}`);
      resultEl.innerHTML = renderDiffResult(data);
    } else {
      const data = await api(`/diff/multi?baseline=${encodeURIComponent(state.diffA)}&candidates=${encodeURIComponent(badList.join(","))}`);
      resultEl.innerHTML = renderDiffMultiResult(data);
    }
  } catch (err) {
    resultEl.innerHTML = emptyStateHtml("Couldn't compute diff", escapeHtml(err.message));
  }
}

function renderDiffResult(data) {
  let html = "";

  if (data.scored_causes && data.scored_causes.length) {
    html += `<div class="causes">
      <div class="causes-title">Likely cause${data.scored_causes.length > 1 ? "s" : ""} (ranked)</div>
      <ul>${data.scored_causes
        .map((c) => `<li>${confidenceBadge(c.confidence)} ${escapeHtml(c.message)}</li>`)
        .join("")}</ul>
    </div>`;
  } else if (data.likely_causes && data.likely_causes.length) {
    html += `<div class="causes">
      <div class="causes-title">Likely cause${data.likely_causes.length > 1 ? "s" : ""}</div>
      <ul>${data.likely_causes.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
    </div>`;
  }

  html += `<div class="panel-title">What changed (${data.narrative.length})</div>`;
  if (data.narrative.length) {
    html += `<div class="card"><ul style="margin:0;padding-left:18px;">${data.narrative
      .map((n) => `<li style="margin-bottom:6px;">${escapeHtml(n)}</li>`)
      .join("")}</ul></div>`;
  } else {
    html += emptyHint("These two runs produced identical traces.");
  }

  data.sections.forEach((section) => {
    if (!section.changed) return;
    html += `<div class="diff-section-title">${escapeHtml(section.name)} <span class="diff-changed-flag">changed</span></div>`;
    section.details.forEach((d) => {
      html += renderDiffDetail(section.name, d);
    });
  });

  return html;
}

function renderDiffMultiResult(data) {
  let html = `<div class="panel-title">Multi-run diff &middot; baseline ${escapeHtml(data.baseline)} vs ${data.candidates.length} candidate(s)</div>`;

  if (data.common_causes && data.common_causes.length) {
    html += `<div class="causes">
      <div class="causes-title">Root cause across all candidates</div>
      <ul>${data.common_causes.map((c) => `<li>${escapeHtml(c)}</li>`).join("")}</ul>
    </div>`;
  } else {
    html += emptyHint("No single cause is common across every candidate run.");
  }

  data.comparisons.forEach((comp) => {
    html += `<div class="diff-section-title">vs ${escapeHtml(comp.run_b)}</div>`;
    html += renderDiffResult(comp);
  });

  return html;
}

function renderDiffDetail(name, d) {
  // The chunks section is a side-by-side table, not a detail card.
  if (name === "chunks") {
    return renderChunkDiff(d);
  }

  switch (name) {
    case "input":
    case "output":
      return `<div class="diff-braid">
        <div class="diff-cell changed good-side">${escapeHtml(d.good)}</div>
        <div class="diff-cell changed bad-side">${escapeHtml(d.bad)}</div>
      </div>`;

    case "retrieval":
      return `<div class="card kv">
        ${
          d.missing_in_bad_run.length
            ? `<div style="margin-bottom:4px;"><span class="k">missing in bad run:</span> ${d.missing_in_bad_run
                .map((x) => `<span class="badge b-retrieval">${escapeHtml(x)}</span>`)
                .join(" ")}</div>`
            : ""
        }
        ${
          d.added_in_bad_run.length
            ? `<div style="margin-bottom:4px;"><span class="k">only in bad run:</span> ${d.added_in_bad_run
                .map((x) => `<span class="badge b-retrieval">${escapeHtml(x)}</span>`)
                .join(" ")}</div>`
            : ""
        }
        ${(d.rank_changes || [])
          .map((rc) => `<div>${escapeHtml(rc.item)}: rank #${rc.good_rank} &rarr; #${rc.bad_rank}</div>`)
          .join("")}
      </div>`;

    case "context":
      return `<div class="card kv">
        ${
          (d.missing_in_bad_run || []).length
            ? `<div style="margin-bottom:4px;"><span class="k">not injected in bad run:</span> ${d.missing_in_bad_run
                .map((x) => `<span class="badge b-context">${escapeHtml(x)}</span>`)
                .join(" ")}</div>`
            : ""
        }
        ${
          (d.added_in_bad_run || []).length
            ? `<div style="margin-bottom:4px;"><span class="k">only injected in bad run:</span> ${d.added_in_bad_run
                .map((x) => `<span class="badge b-context">${escapeHtml(x)}</span>`)
                .join(" ")}</div>`
            : ""
        }
        ${(d.reordered || [])
          .map((rc) => `<div>${escapeHtml(rc.key)}: position ${rc.good_position} &rarr; ${rc.bad_position}</div>`)
          .join("")}
        ${(d.value_changed || [])
          .map(
            (cv) => `<div class="diff-braid" style="margin-top:6px;">
              <div class="diff-cell changed good-side">${escapeHtml(cv.key)}: ${escapeHtml(cv.good_content)}</div>
              <div class="diff-cell changed bad-side">${escapeHtml(cv.key)}: ${escapeHtml(cv.bad_content)}</div>
            </div>`
          )
          .join("")}
      </div>`;

    case "prompt": {
      let out = renderTokenDiff(d.token_diff);
      out += `<div class="diff-braid">
        <div class="diff-cell ${d.good_system !== d.bad_system ? "changed" : ""} good-side">${escapeHtml(
        d.good_system || "(none)"
      )}</div>
        <div class="diff-cell ${d.good_system !== d.bad_system ? "changed" : ""} bad-side">${escapeHtml(
        d.bad_system || "(none)"
      )}</div>
      </div>`;
      if (JSON.stringify(d.good_messages) !== JSON.stringify(d.bad_messages)) {
        out += `<div class="diff-braid" style="margin-top:8px;">
          <div class="diff-cell changed good-side">${jsonPretty(d.good_messages)}</div>
          <div class="diff-cell changed bad-side">${jsonPretty(d.bad_messages)}</div>
        </div>`;
      }
      return out;
    }

    case "tools":
      return `<div class="diff-braid">
        <div class="diff-cell changed good-side">${jsonPretty(d.good)}</div>
        <div class="diff-cell changed bad-side">${jsonPretty(d.bad)}</div>
      </div>`;

    case "memory":
      return `<div class="card kv"><span class="k">${escapeHtml(d.key)}:</span> ${escapeHtml(
        jsonInline(d.good_value)
      )} &rarr; ${escapeHtml(jsonInline(d.bad_value))}</div>`;

    default:
      return `<div class="card"><pre class="raw">${jsonPretty(d)}</pre></div>`;
  }
}

/* -------------------------------------------------------------------- */
/* Memory Chunk Diff -- side-by-side chunk comparison                      */
/* -------------------------------------------------------------------- */

const CHUNK_STATUS_META = {
  added: { label: "newly retrieved", cls: "chunk-added" },
  removed: { label: "removed", cls: "chunk-removed" },
  newly_selected: { label: "newly selected", cls: "chunk-newly-selected" },
  deselected: { label: "deselected", cls: "chunk-deselected" },
  rank_changed: { label: "rank changed", cls: "chunk-rank-changed" },
  score_changed: { label: "score changed", cls: "chunk-score-changed" },
};

function chunkStatusBadge(status) {
  const meta = CHUNK_STATUS_META[status];
  if (!meta) return "";
  return `<span class="chunk-status ${meta.cls}">${meta.label}</span>`;
}

function chunkScoreCell(v, highlight) {
  if (v === null || v === undefined) return `<td class="mono chunk-empty">\u2014</td>`;
  return `<td class="mono ${highlight ? "chunk-highlight" : ""}">${escapeHtml(v)}</td>`;
}

function chunkRankCell(v, highlight) {
  if (v === null || v === undefined) return `<td class="mono chunk-empty">\u2014</td>`;
  return `<td class="mono ${highlight ? "chunk-highlight" : ""}"><span class="rank-pill">#${escapeHtml(v)}</span></td>`;
}

function chunkSelectedCell(v) {
  if (v === true) return `<td><span class="chunk-selected">\u2713 selected</span></td>`;
  if (v === false) return `<td><span class="chunk-rejected">\u2717 rejected</span></td>`;
  return `<td class="chunk-empty">\u2014</td>`;
}

function chunkDeltaCell(delta) {
  if (delta === null || delta === undefined) return `<td class="mono chunk-empty">\u2014</td>`;
  const cls = delta > 0 ? "chunk-delta-up" : delta < 0 ? "chunk-delta-down" : "chunk-delta-flat";
  const sign = delta > 0 ? "+" : "";
  return `<td class="mono ${cls}">${sign}${escapeHtml(delta)}</td>`;
}

function renderChunkDiff(rows) {
  const rowHtml = rows
    .map((r) => {
      const good = r.good || {};
      const bad = r.bad || {};
      // Highlight rank/score cells whenever the values differ between runs,
      // regardless of the primary status tag (e.g. a chunk can be both
      // newly selected AND moved from rank #7 to rank #1).
      const rankChanged = good.rank !== undefined && bad.rank !== undefined && good.rank !== bad.rank;
      const scoreChanged = good.score !== undefined && bad.score !== undefined && good.score !== bad.score;

      // Replacement callout: "Chunk A replaced Chunk B."
      let replacement = "";
      if (r.replaced_by) {
        replacement = `<div class="chunk-replacement">Chunk <span class="mono">${escapeHtml(
          r.chunk_id
        )}</span> replaced Chunk <span class="mono">${escapeHtml(r.replaced_by)}</span> in the final prompt.</div>`;
      } else if (r.replaces) {
        replacement = `<div class="chunk-replacement">Chunk <span class="mono">${escapeHtml(
          r.replaces
        )}</span> was replaced by Chunk <span class="mono">${escapeHtml(r.chunk_id)}</span> in the final prompt.</div>`;
      }

      return `
      <tr class="chunk-row ${r.status}">
        <td>
          <div class="chunk-id-row">
            <span class="mono chunk-id">${escapeHtml(r.chunk_id)}</span>
            ${chunkStatusBadge(r.status)}
          </div>
          <div class="chunk-source">${escapeHtml(r.source || "")}</div>
          ${replacement}
        </td>
        <td class="chunk-side good-side">
          ${chunkRankCell(good.rank, rankChanged)}
          ${chunkScoreCell(good.score, scoreChanged)}
          ${chunkScoreCell(good.rerank_score, false)}
          ${chunkSelectedCell(good.selected)}
        </td>
        <td class="chunk-side bad-side">
          ${chunkRankCell(bad.rank, rankChanged)}
          ${chunkScoreCell(bad.score, scoreChanged)}
          ${chunkScoreCell(bad.rerank_score, false)}
          ${chunkSelectedCell(bad.selected)}
        </td>
        <td>${chunkDeltaCell(r.similarity_delta)}</td>
      </tr>`;
    })
    .join("");

  return `
    <div class="card chunk-diff-card">
      <div class="scroll-x">
      <table class="chunk-diff">
        <thead>
          <tr>
            <th class="chunk-col-id">Chunk</th>
            <th class="chunk-col-side">
              <span class="diff-col-head good" style="border:none;padding:0;margin:0;">good run</span>
              <div class="chunk-subhead">rank &middot; score &middot; rerank &middot; state</div>
            </th>
            <th class="chunk-col-side">
              <span class="diff-col-head bad" style="border:none;padding:0;margin:0;">bad run</span>
              <div class="chunk-subhead">rank &middot; score &middot; rerank &middot; state</div>
            </th>
            <th class="chunk-col-delta">\u0394 score</th>
          </tr>
        </thead>
        <tbody>${rowHtml}</tbody>
      </table>
      </div>
    </div>`;
}

/* -------------------------------------------------------------------- */
/* Clear logs                                                             */
/* -------------------------------------------------------------------- */

async function clearLogs() {
  const btn = document.getElementById("clear-logs-btn");
  if (!btn) return;
  if (!state.runs.length) return;

  if (!window.confirm("Delete all runs and events? This cannot be undone.")) return;

  btn.disabled = true;
  btn.textContent = "Clearing\u2026";
  try {
    await api("/runs", { method: "DELETE" });
    state.runs = [];
    state.selectedRunId = null;
    state.diffA = null;
    state.diffB = null;
    renderRunList();
    document.getElementById("content").innerHTML = emptyStateHtml(
      "No run selected",
      "Instrument a run with the Python SDK, then pick it up on the left."
    );
  } catch (err) {
    window.alert("Failed to clear logs: " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Clear Logs";
  }
}

document.getElementById("clear-logs-btn").addEventListener("click", clearLogs);

/* -------------------------------------------------------------------- */
/* Boot + polling                                                         */
/* -------------------------------------------------------------------- */

async function refreshRuns() {
  try {
    const runs = await api("/runs");
    state.runs = runs;
    if (!state.selectedRunId && runs.length) {
      state.selectedRunId = runs[0].id;
    }
    renderRunList();
    document.getElementById("conn-dot").classList.remove("down");
    document.getElementById("conn-dot").classList.add("live");
    if (state.activeTab !== "diff") {
      await renderActiveTab();
    }
  } catch (err) {
    document.getElementById("conn-dot").classList.remove("live");
    document.getElementById("conn-dot").classList.add("down");
  }
}

async function init() {
  try {
    const health = await api("/health");
    document.getElementById("db-path").textContent = health.db;
  } catch (err) {
    document.getElementById("db-path").textContent = "server unreachable";
  }
  await refreshRuns();

  // Deep-link to a tab via the URL hash, e.g. /#diff
  const hashTab = location.hash.replace("#", "");
  if (hashTab) {
    const tabBtn = document.querySelector(`.tab[data-tab="${hashTab}"]`);
    if (tabBtn) tabBtn.click();
  }

  setInterval(refreshRuns, 4000);
}

init();
