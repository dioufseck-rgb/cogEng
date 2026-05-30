const state = {
  projection: null,
  view: "overview",
  selected: null,
};

const byId = (id) => document.getElementById(id);

fetch("./projection.json")
  .then((response) => {
    if (!response.ok) throw new Error(`projection load failed: ${response.status}`);
    return response.json();
  })
  .then((projection) => {
    state.projection = projection;
    state.selected = projection.case_results?.[0] || projection.timeline?.[0] || null;
    bindNavigation();
    renderShell();
    render();
  })
  .catch((error) => {
    byId("primary-panel").innerHTML = panel("Load error", `<pre>${escapeHtml(error.message)}</pre>`);
  });

function bindNavigation() {
  document.querySelectorAll(".rail-item").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".rail-item").forEach((item) => item.classList.remove("active"));
      button.classList.add("active");
      state.view = button.dataset.view;
      state.selected = defaultSelection(state.view);
      render();
    });
  });
}

function renderShell() {
  const projection = state.projection;
  byId("workspace-name").textContent = projection.workspace.name;
  byId("trajectory-id").textContent = projection.trajectory.trajectory_id;
  byId("validation-status").textContent = projection.trajectory.validation_ok ? "Validation ok" : "Validation issue";
  byId("validation-status").classList.toggle("warn", !projection.trajectory.validation_ok);
  byId("active-branch").textContent = `Active ${projection.trajectory.active_branch_id}`;
  byId("metric-events").textContent = projection.trajectory.event_count;
  byId("metric-branches").textContent = projection.branches.length;
  byId("metric-cases").textContent = projection.cases?.length || projection.case_results.length;
  byId("metric-reports").textContent = projection.reports.length;
}

function render() {
  const titles = {
    overview: "Overview",
    program: "Program",
    graph: "DAG",
    cases: "Cases",
    map: "Map",
    actions: "Actions",
    timeline: "Timeline",
    reports: "Reports",
  };
  byId("page-title").textContent = titles[state.view] || "Overview";
  const viewRenderers = {
    overview: renderOverview,
    program: renderProgram,
    graph: renderGraph,
    cases: renderCases,
    map: renderMap,
    actions: renderActions,
    timeline: renderTimeline,
    reports: renderReports,
  };
  (viewRenderers[state.view] || renderOverview)();
}

function renderOverview() {
  const projection = state.projection;
  const program = projection.program || {};
  byId("primary-panel").innerHTML = panel(
    "Program Snapshot",
    `<div class="panel-body">
      <div class="list">
        ${kv("Program", program.name || "Unknown")}
        ${kv("Snapshot", program.snapshot_id || "None")}
        ${kv("Atoms", program.atom_count ?? 0)}
        ${kv("Determinations", program.determination_count ?? 0)}
        ${kv("Nodes", program.node_count ?? 0)}
      </div>
    </div>`
  );
  byId("detail-panel").innerHTML = panel(
    "Branches",
    `<div class="panel-body"><div class="list">${projection.branches.map(branchItem).join("")}</div></div>`
  );
}

function renderProgram() {
  const program = state.projection.program || {};
  const atoms = program.atoms || [];
  const nodes = program.nodes || [];
  byId("primary-panel").innerHTML = panel(
    "Atoms",
    `<div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Atom</th>
            <th>Type</th>
            <th>Mode</th>
            <th>Statement</th>
          </tr>
        </thead>
        <tbody>${atoms.map(atomRow).join("")}</tbody>
      </table>
    </div>`
  );
  byId("detail-panel").innerHTML = panel(
    "DAG Nodes",
    `<div class="panel-body"><div class="list">${nodes.map(nodeItem).join("")}</div></div>`
  );
}

function renderGraph() {
  const program = state.projection.program || {};
  const determinations = program.determinations || [];
  const selected = state.selected || determinations[0] || null;
  state.selected = selected;
  const rootNodeId = selected ? determinationRootNode(selected, determinations) : null;
  byId("primary-panel").innerHTML = panel(
    "Determinations",
    `<div class="graph-layout">
      <div class="det-list">${determinations.map(detItem).join("")}</div>
      <div class="dag-tree">${rootNodeId ? renderDagTree(rootNodeId) : `<span class="meta">No determination selected</span>`}</div>
    </div>`
  );
  byId("detail-panel").innerHTML = panel(
    selected?.composition === "complement" ? "Complement Detail" : "Node Detail",
    `<div class="panel-body"><pre>${escapeHtml(JSON.stringify(selected, null, 2))}</pre></div>`
  );
}

function renderCases() {
  const rows = state.projection.cases || state.projection.case_results || [];
  byId("primary-panel").innerHTML = panel(
    "Cases",
    `<div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Results</th>
            <th>Expected</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>${rows.map(caseRow).join("")}</tbody>
      </table>
    </div>`
  );
  renderDetail(state.selected || rows[0]);
}

function renderMap() {
  const records = state.projection.map_records || [];
  const hints = state.projection.reviewer_hints || [];
  byId("primary-panel").innerHTML = panel(
    "Map Records",
    `<div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Substrate</th>
            <th>Bindings</th>
            <th>Hints</th>
          </tr>
        </thead>
        <tbody>${records.map(mapRecordRow).join("")}</tbody>
      </table>
    </div>`
  );
  byId("detail-panel").innerHTML = panel(
    "Reviewer Hints",
    `<div class="panel-body"><div class="list">${hints.length ? hints.map(hintItem).join("") : `<span class="meta">No reviewer hints recorded</span>`}</div></div>`
  );
}

function renderActions() {
  const apiBase = localStorage.getItem("rulekitApiBase") || window.location.origin;
  byId("primary-panel").innerHTML = panel(
    "Reviewer Hint",
    `<form class="action-form" onsubmit="submitHint(event)">
      <label>API base<input name="apiBase" value="${escapeHtml(apiBase)}" /></label>
      <label>Message<textarea name="message" rows="4" required></textarea></label>
      <div class="form-grid">
        <label>Case ID<input name="caseId" /></label>
        <label>Atom ID<input name="atomId" /></label>
      </div>
      <label class="checkline"><input type="checkbox" name="reexercise" checked /> Reexercise after recording</label>
      <button class="primary-action" type="submit">Record hint</button>
    </form>`
  );
  byId("detail-panel").innerHTML = panel(
    "Add Case",
    `<form class="action-form" onsubmit="submitCase(event)">
      <label>Title<input name="title" required /></label>
      <label>Narrative<textarea name="narrative" rows="5" required></textarea></label>
      <label>Facts JSON<textarea name="facts" rows="4" placeholder='{"atom.id": true}'></textarea></label>
      <label>Expected JSON<textarea name="expected" rows="3" placeholder='{"determination.id": "true"}'></textarea></label>
      <label class="checkline"><input type="checkbox" name="reexercise" checked /> Reexercise after adding</label>
      <button class="primary-action" type="submit">Add case</button>
    </form>`
  );
}

function renderTimeline() {
  const events = state.projection.timeline || [];
  byId("primary-panel").innerHTML = panel(
    "Trajectory Timeline",
    `<div class="panel-body"><div class="list">${events.map(eventItem).join("")}</div></div>`
  );
  renderDetail(state.selected || events[0]);
}

function renderReports() {
  const reports = state.projection.reports || [];
  byId("primary-panel").innerHTML = panel(
    "Governance Reports",
    `<div class="panel-body"><div class="list">${reports.map(reportItem).join("")}</div></div>`
  );
  renderDetail(state.selected || reports[0]);
}

function renderDetail(item) {
  state.selected = item || null;
  if (!item) {
    byId("detail-panel").innerHTML = panel("Detail", `<div class="panel-body"><span class="meta">No selection</span></div>`);
    return;
  }
  byId("detail-panel").innerHTML = panel(
    "Detail",
    `<div class="panel-body"><pre>${escapeHtml(JSON.stringify(item, null, 2))}</pre></div>`
  );
}

function caseRow(row) {
  const status = caseStatus(row);
  return `<tr>
    <td><button class="row-button" onclick='selectItem(${jsonAttr(row)})'>${escapeHtml(row.title || row.case_title || row.case_id)}</button></td>
    <td>${escapeHtml(caseResultSummary(row))}</td>
    <td>${escapeHtml(expectedSummary(row))}</td>
    <td><span class="tag ${status.className}">${status.label}</span></td>
  </tr>`;
}

function caseResultSummary(row) {
  if (Array.isArray(row.outcomes)) {
    if (!row.outcomes.length) return "Not run";
    return row.outcomes
      .map((outcome) => `${outcome.determination_id}: ${outcome.outcome}`)
      .join("; ");
  }
  return row.determination_id ? `${row.determination_id}: ${row.outcome}` : "Not run";
}

function expectedSummary(row) {
  if (row.expected_outcomes && !Array.isArray(row.expected_outcomes)) {
    const entries = Object.entries(row.expected_outcomes);
    return entries.length ? entries.map(([key, value]) => `${key}: ${value}`).join("; ") : "";
  }
  return row.expected_outcome || "";
}

function caseStatus(row) {
  if (Array.isArray(row.outcomes) && !row.outcomes.length) {
    return {className: "neutral", label: "Not run"};
  }
  if (row.matched_expected === true) return {className: "ok", label: "Matched"};
  if (row.matched_expected === false) return {className: "fail", label: "Mismatch"};
  return {className: "neutral", label: "No expected"};
}

function atomRow(atom) {
  return `<tr>
    <td><button class="row-button" onclick='selectItem(${jsonAttr(atom)})'>${escapeHtml(atom.atom_id)}</button></td>
    <td>${escapeHtml(atom.atom_type)}</td>
    <td>${escapeHtml(atom.evaluation_mode || "")}</td>
    <td>${escapeHtml(atom.statement)}</td>
  </tr>`;
}

function detItem(det) {
  return `<button class="det-item ${state.selected?.determination_id === det.determination_id ? "active" : ""}" onclick='selectDetermination(${jsonAttr(det)})'>
    <span class="det-title">${escapeHtml(det.determination_id)}</span>
    <span class="meta">${escapeHtml(det.composition)}${det.root_node ? ` - ${escapeHtml(det.root_node)}` : ""}</span>
  </button>`;
}

function renderDagTree(rootNodeId) {
  const program = state.projection.program || {};
  const nodes = Object.fromEntries((program.nodes || []).map((node) => [node.node_id, node]));
  const atoms = Object.fromEntries((program.atoms || []).map((atom) => [atom.atom_id, atom]));
  const counts = childRefCounts(nodes);
  const seen = new Set();
  const lines = [];

  function emit(nodeId, prefix, isLast, isRoot) {
    const node = nodes[nodeId];
    if (!node) {
      lines.push(`<div class="dag-row"><span class="guides">${escapeHtml(prefix)}</span><span class="meta">Missing node ${escapeHtml(nodeId || "")}</span></div>`);
      return;
    }
    const already = seen.has(nodeId);
    seen.add(nodeId);
    const guide = isRoot ? "" : `${prefix}${isLast ? "`- " : "|- "}`;
    const childPrefix = isRoot ? "" : `${prefix}${isLast ? "   " : "|  "}`;
    const children = nodeChildren(node);
    const label = nodeLabel(node, atoms);
    const shared = counts[nodeId] > 1;
    lines.push(`<div class="dag-row">
      <span class="guides">${escapeHtml(guide)}</span>
      <button class="dag-node" onclick='selectNode(${jsonAttr(node)})'>
        <span class="op ${opClass(node.kind)}">${escapeHtml(opLabel(node))}</span>
        <span class="dag-label">${escapeHtml(label)}</span>
        ${shared ? `<span class="shared-tag">shared</span>` : ""}
        <span class="node-id">${escapeHtml(nodeId)}</span>
      </button>
    </div>`);
    if (already && !isRoot) {
      lines.push(`<div class="dag-row dim"><span class="guides">${escapeHtml(childPrefix)}   </span><span class="meta">expanded above</span></div>`);
      return;
    }
    children.forEach((childId, index) => emit(childId, childPrefix, index === children.length - 1, false));
  }

  emit(rootNodeId, "", true, true);
  return lines.join("");
}

function mapRecordRow(record) {
  const statuses = Object.entries(record.status_counts || {})
    .map(([status, count]) => `${status}:${count}`)
    .join(", ");
  return `<tr>
    <td><button class="row-button" onclick='selectItem(${jsonAttr(record)})'>${escapeHtml(record.case_id)}</button></td>
    <td>${escapeHtml(record.substrate_id)}</td>
    <td>${escapeHtml(statuses || String(record.binding_count || 0))}</td>
    <td>${escapeHtml(record.reviewer_hint_count || 0)}</td>
  </tr>`;
}

function eventItem(event) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(event)})'>
      <div class="list-title">${escapeHtml(event.title)}</div>
      <div class="meta">${escapeHtml(event.kind)} - ${escapeHtml(event.branch_id)}</div>
    </button>
  </div>`;
}

function reportItem(report) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(report)})'>
      <div class="list-title">${escapeHtml(report.headline)}</div>
      <div class="meta">${escapeHtml(report.kind)} - ${escapeHtml(report.report_id)}</div>
    </button>
  </div>`;
}

function nodeItem(node) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(node)})'>
      <div class="list-title">${escapeHtml(node.node_id)}</div>
      <div class="meta">${escapeHtml(node.kind)}${node.surface_label ? ` - ${escapeHtml(node.surface_label)}` : ""}</div>
    </button>
  </div>`;
}

function selectDetermination(det) {
  state.selected = det;
  renderGraph();
}

function selectNode(node) {
  byId("detail-panel").innerHTML = panel(
    "Node Detail",
    `<div class="panel-body"><pre>${escapeHtml(JSON.stringify(node, null, 2))}</pre></div>`
  );
}

function determinationRootNode(det, determinations) {
  if (det.root_node) return det.root_node;
  if (!det.linked_to) return null;
  const linked = determinations.find((item) => item.determination_id === det.linked_to);
  return linked?.root_node || null;
}

function nodeChildren(node) {
  const children = [];
  if (Array.isArray(node.children)) children.push(...node.children);
  ["child", "left", "right", "condition", "if_true", "if_false"].forEach((key) => {
    if (node[key]) children.push(node[key]);
  });
  return children;
}

function childRefCounts(nodes) {
  const counts = {};
  Object.values(nodes).forEach((node) => {
    nodeChildren(node).forEach((childId) => {
      counts[childId] = (counts[childId] || 0) + 1;
    });
  });
  return counts;
}

function opLabel(node) {
  if (node.kind === "comparison") return cmpSymbol(node.operator);
  if (node.kind === "atom_ref") return "ATOM";
  if (node.kind === "numeric_atom_ref") return "NUM";
  if (node.kind === "constant") return "CONST";
  if (node.kind === "named_quantity") return "QTY";
  if (node.kind === "binary_arithmetic") return node.operator || "BIN";
  if (node.kind === "unary_arithmetic") return node.operator || "UN";
  if (node.kind === "variadic_arithmetic") return node.operator || "VAR";
  return String(node.kind || "").replace("_", " ").toUpperCase();
}

function opClass(kind) {
  if (kind === "and" || kind === "at_least") return "and";
  if (kind === "or") return "or";
  if (kind === "not") return "not";
  if (kind === "comparison") return "cmp";
  if (kind === "atom_ref" || kind === "numeric_atom_ref") return "atom";
  return "other";
}

function nodeLabel(node, atoms) {
  if (node.surface_label) return node.surface_label;
  if (node.atom_id) return atoms[node.atom_id]?.statement || human(node.atom_id);
  if (node.kind === "constant") return node.literal_value ?? node.constant_label ?? "constant";
  if (node.kind === "comparison") return `${node.left} ${cmpSymbol(node.operator)} ${node.right}`;
  if (node.kind === "conditional_numeric") return `if ${node.condition}`;
  return node.kind || node.node_id;
}

function cmpSymbol(operator) {
  return {eq: "=", lt: "<", leq: "<=", gt: ">", geq: ">="}[operator] || operator || "CMP";
}

function human(value) {
  return String(value || "").replaceAll("_", " ").replaceAll(".", " ");
}

function hintItem(hint) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(hint)})'>
      <div class="list-title">${escapeHtml(hint.case_id || hint.target_step_id || "General hint")}</div>
      <div class="meta">${escapeHtml(hint.message)}</div>
    </button>
  </div>`;
}

function branchItem(branch) {
  return `<div class="list-item">
    <div class="list-title">${escapeHtml(branch.branch_id)}</div>
    <div class="meta">${escapeHtml(branch.status)}${branch.is_active ? " - active" : ""}</div>
  </div>`;
}

function selectItem(item) {
  renderDetail(item);
}

async function submitHint(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const atomIds = data.atomId ? [data.atomId] : [];
    const payload = {
      message: data.message,
      target_step_id: "map_prebound_facts",
      case_id: data.caseId || null,
      atom_ids: atomIds,
      reexercise: form.reexercise.checked,
    };
    await postAction(data.apiBase, "hints", payload);
  } catch (error) {
    renderDetail({error: error.message});
  }
}

async function submitCase(event) {
  event.preventDefault();
  try {
    const form = event.currentTarget;
    const data = Object.fromEntries(new FormData(form).entries());
    const payload = {
      title: data.title,
      narrative: data.narrative,
      facts: parseJsonObject(data.facts, "Facts JSON"),
      expected_outcomes: parseJsonObject(data.expected, "Expected JSON"),
      reexercise: form.reexercise.checked,
    };
    const apiBase = localStorage.getItem("rulekitApiBase") || window.location.origin;
    await postAction(apiBase, "cases", payload);
  } catch (error) {
    renderDetail({error: error.message});
  }
}

async function postAction(apiBase, action, payload) {
  localStorage.setItem("rulekitApiBase", apiBase);
  const projection = state.projection;
  const base = apiBase.replace(/\/$/, "");
  const url = `${base}/workspaces/${projection.workspace.workspace_id}/trajectories/${projection.trajectory.trajectory_id}/${action}`;
  const response = await fetch(url, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  if (!response.ok || body.ok === false) {
    renderDetail({error: "Action failed", status: response.status, body});
    return;
  }
  await refreshProjection();
  if (action === "cases") {
    state.view = "cases";
    state.selected = selectCaseFromProjection(body.case_id) || defaultSelection("cases");
    setActiveRail("cases");
  }
  render();
  renderDetail(body);
}

async function refreshProjection() {
  const response = await fetch("./projection.json", {cache: "no-store"});
  if (!response.ok) throw new Error(`projection refresh failed: ${response.status}`);
  state.projection = await response.json();
  renderShell();
}

function selectCaseFromProjection(caseId) {
  if (!caseId) return null;
  return (state.projection.cases || []).find((row) => row.case_id === caseId) || null;
}

function setActiveRail(view) {
  document.querySelectorAll(".rail-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
}

function parseJsonObject(value, label) {
  if (!value || !value.trim()) return {};
  const parsed = JSON.parse(value);
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed;
}

function defaultSelection(view) {
  const projection = state.projection;
  if (view === "program") return projection.program?.atoms?.[0] || projection.program || null;
  if (view === "graph") return projection.program?.determinations?.[0] || null;
  if (view === "cases") return projection.cases?.[0] || projection.case_results?.[0] || null;
  if (view === "map") return projection.map_records?.[0] || projection.reviewer_hints?.[0] || null;
  if (view === "actions") return null;
  if (view === "timeline") return projection.timeline?.[0] || null;
  if (view === "reports") return projection.reports?.[0] || null;
  return projection.program || null;
}

function panel(title, body) {
  return `<div class="panel-header"><h3>${escapeHtml(title)}</h3></div>${body}`;
}

function kv(label, value) {
  return `<div class="list-item">
    <div class="meta">${escapeHtml(label)}</div>
    <div class="list-title">${escapeHtml(String(value))}</div>
  </div>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function jsonAttr(value) {
  return escapeHtml(JSON.stringify(value));
}
