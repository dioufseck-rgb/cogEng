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
  byId("metric-cases").textContent = projection.case_results.length;
  byId("metric-reports").textContent = projection.reports.length;
}

function render() {
  const titles = {
    overview: "Overview",
    cases: "Cases",
    timeline: "Timeline",
    reports: "Reports",
  };
  byId("page-title").textContent = titles[state.view] || "Overview";
  const viewRenderers = {
    overview: renderOverview,
    cases: renderCases,
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

function renderCases() {
  const rows = state.projection.case_results || [];
  byId("primary-panel").innerHTML = panel(
    "Case Results",
    `<div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Case</th>
            <th>Determination</th>
            <th>Outcome</th>
            <th>Expected</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(caseRow).join("")}
        </tbody>
      </table>
    </div>`
  );
  renderDetail(state.selected || rows[0]);
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
  const status = row.matched_expected ? "ok" : "fail";
  const label = row.matched_expected ? "Matched" : "Mismatch";
  return `<tr>
    <td><button class="row-button" onclick='selectItem(${jsonAttr(row)})'>${escapeHtml(row.case_title || row.case_id)}</button></td>
    <td>${escapeHtml(row.determination_id)}</td>
    <td>${escapeHtml(row.outcome)}</td>
    <td>${escapeHtml(row.expected_outcome || "")}</td>
    <td><span class="tag ${status}">${label}</span></td>
  </tr>`;
}

function eventItem(event) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(event)})'>
      <div class="list-title">${escapeHtml(event.title)}</div>
      <div class="meta">${escapeHtml(event.kind)} · ${escapeHtml(event.branch_id)}</div>
    </button>
  </div>`;
}

function reportItem(report) {
  return `<div class="list-item">
    <button onclick='selectItem(${jsonAttr(report)})'>
      <div class="list-title">${escapeHtml(report.headline)}</div>
      <div class="meta">${escapeHtml(report.kind)} · ${escapeHtml(report.report_id)}</div>
    </button>
  </div>`;
}

function branchItem(branch) {
  return `<div class="list-item">
    <div class="list-title">${escapeHtml(branch.branch_id)}</div>
    <div class="meta">${escapeHtml(branch.status)}${branch.is_active ? " · active" : ""}</div>
  </div>`;
}

function selectItem(item) {
  renderDetail(item);
}

function defaultSelection(view) {
  const projection = state.projection;
  if (view === "cases") return projection.case_results?.[0] || null;
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
