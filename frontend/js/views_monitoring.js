/* Sections 31-37 -- Incident Management, Alert Management, Risk Engine,
   Traceability Explorer. Section 27 Override System. */
var Views = window.Views || {};
Views.monitoring = {

  async live() {
    const [runsResp, machinesResp] = await Promise.all([Api.get("/v1/runs?status_=RUNNING"), Api.get("/v1/machines")]);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Live Production</h2></div>
      <div class="grid-2">
        <div class="card"><h3>Running Machines</h3>
          ${dataTable([
            { label: "Machine", key: "name" }, { label: "Status", render: (m) => `${statusBadge(m.status)} ${m.isStale ? '<span class="badge badge-yellow">STALE</span>' : ""}` },
            { label: "Last Update", render: (m) => timeAgo(m.lastHeartbeatAt) },
          ], machinesResp.items.filter((m) => m.status === "RUNNING"), { emptyText: "No machines currently running." })}
        </div>
        <div class="card"><h3>Active Runs</h3>
          ${dataTable([
            { label: "Run", key: "code" }, { label: "Order", key: "orderCode" }, { label: "Machine", key: "machineName" },
            { label: "Status", render: (r) => `${statusBadge(r.status)} ${r.isStale ? '<span class="badge badge-yellow">STALE</span>' : ""}` },
          ], runsResp.items, { emptyText: "No active runs." })}
        </div>
      </div>
    `;
  },

  // ---------------- Alerts (Sections 33-34) ----------------

  async alerts() {
    const d = await Api.get("/v1/alerts");
    const canManage = Auth.hasPerm("MANAGE_ALERTS");
    const content = document.getElementById("content");
    const openAlerts = d.items.filter((a) => !["RESOLVED", "DISMISSED"].includes(a.status));
    const closedAlerts = d.items.filter((a) => ["RESOLVED", "DISMISSED"].includes(a.status));
    content.innerHTML = `
      <div class="page-header"><h2>Alerts</h2></div>
      <div class="card"><h3>Active (${openAlerts.length})</h3>
        ${dataTable([
          { label: "Severity", render: (a) => statusBadge(a.severity) }, { label: "Type", key: "type" }, { label: "Message", key: "message" },
          { label: "Status", render: (a) => `${statusBadge(a.status)} ${a.escalated ? '<span class="badge badge-red">ESCALATED</span>' : ""}` },
          { label: "SLA Due", render: (a) => fmtDate(a.slaDueAt) }, { label: "Created", render: (a) => timeAgo(a.createdAt) },
          { label: "", render: (a) => canManage ? this.alertActions(a) : "" },
        ], openAlerts, { emptyText: "No active alerts." })}
      </div>
      <div class="card"><h3>Resolved / Dismissed</h3>
        ${dataTable([
          { label: "Severity", render: (a) => statusBadge(a.severity) }, { label: "Type", key: "type" }, { label: "Message", key: "message" },
          { label: "Status", render: (a) => statusBadge(a.status) }, { label: "Created", render: (a) => fmtDate(a.createdAt) },
        ], closedAlerts.slice(0, 20), { emptyText: "None yet." })}
      </div>
    `;
    if (canManage) content.querySelectorAll("[data-alert-act]").forEach((b) => b.addEventListener("click", () => this.alertAction(b.dataset.alertAct, b.dataset.id)));
  },

  alertActions(a) {
    const map = { NEW: [["Acknowledge", "ACKNOWLEDGED"]], ACKNOWLEDGED: [["Start Work", "IN_PROGRESS"], ["Dismiss", "DISMISSED"]], IN_PROGRESS: [["Resolve", "RESOLVED"], ["Dismiss", "DISMISSED"]] };
    return (map[a.status] || []).map(([label, to]) => `<button class="btn btn-sm" data-alert-act="${to}" data-id="${a.id}">${label}</button>`).join(" ");
  },

  async alertAction(toState, id) {
    let reason;
    if (toState === "DISMISSED") reason = prompt("Reason for dismissal?") || "";
    try { await Api.post(`/v1/alerts/${id}/transitions`, { toState, reason }); toast(`Alert -> ${toState}.`, "success"); App.route(); }
    catch (err) { notifyError(err); }
  },

  // ---------------- Risks (Section 36) ----------------

  async risks() {
    const d = await Api.get("/v1/risk-scores");
    const content = document.getElementById("content");
    const sorted = d.items.sort((a, b) => b.score - a.score);
    content.innerHTML = `
      <div class="page-header"><h2>Risk Scores</h2></div>
      <p class="flow-note">Section 36.1: within a category (Schedule, Resource, Machine Health, Quality) only the worst active factor counts; categories then sum, capped at 100.</p>
      <div class="card">${dataTable([
        { label: "Entity", render: (r) => `${r.entityType} / ${r.entityId.slice(0, 8)}` },
        { label: "Score", render: (r) => `<div style="width:140px">${riskBar(r.score, r.classification)}</div>` },
        { label: "Classification", render: (r) => statusBadge(r.classification) },
        { label: "Contributing Factors", render: (r) => r.contributingFactors.map((f) => `<span class="badge badge-gray" style="margin-right:4px">${esc(f.factorCode)} (+${f.score})</span>`).join("") || "-" },
        { label: "Calculated", render: (r) => timeAgo(r.calculatedAt) },
      ], sorted, { emptyText: "No risk scores calculated yet." })}</div>
    `;
  },

  // ---------------- Incidents (Sections 31-32) ----------------

  INCIDENT_TRANSITIONS: {
    OPEN: ["UNDER_INVESTIGATION", "CLOSED"], UNDER_INVESTIGATION: ["ACTION_REQUIRED", "CLOSED"],
    ACTION_REQUIRED: ["CORRECTIVE_ACTION"], CORRECTIVE_ACTION: ["VERIFICATION"],
    VERIFICATION: ["CLOSED", "UNDER_INVESTIGATION"], CLOSED: ["REOPENED"], REOPENED: ["UNDER_INVESTIGATION"],
  },

  async incidents() {
    const d = await Api.get("/v1/incidents");
    const canManage = Auth.hasPerm("MANAGE_INCIDENTS");
    const canReport = Auth.hasPerm("MANAGE_INCIDENTS", "REPORT_INCIDENTS");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Incidents</h2><div class="page-actions">${canReport ? `<button class="btn btn-primary" id="new-incident-btn">+ Report Incident</button>` : ""}</div></div>
      <div class="card">${dataTable([
        { label: "Code", key: "code" }, { label: "Type", key: "type" }, { label: "Severity", render: (i) => statusBadge(i.severity) },
        { label: "Status", render: (i) => statusBadge(i.status) }, { label: "Detected", render: (i) => fmtDate(i.detectedAt) },
        { label: "Description", key: "description" },
        { label: "", render: (i) => canManage ? `<button class="btn btn-sm" data-incident="${i.id}">Manage</button>` : "" },
      ], d.items, { emptyText: "No incidents." })}</div>
    `;
    if (canReport) document.getElementById("new-incident-btn").addEventListener("click", () => this.newIncidentModal());
    if (canManage) content.querySelectorAll("[data-incident]").forEach((b) => b.addEventListener("click", () => this.openIncidentModal(b.dataset.incident, d.items)));
  },

  newIncidentModal() {
    openModal({
      title: "Report Incident",
      bodyHtml: `<form id="inc-form"><div class="form-grid">
        <div class="field"><label>Type</label><input name="type" required /></div>
        <div class="field"><label>Severity</label><select name="severity"><option>LOW</option><option>MEDIUM</option><option>HIGH</option><option>CRITICAL</option></select></div>
        <div class="field span-2"><label>Description</label><textarea name="description" required></textarea></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Submit</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/incidents", formToObject(document.getElementById("inc-form"))); closeModal(); toast("Incident reported.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  openIncidentModal(id, items) {
    const inc = items.find((i) => i.id === id);
    const legal = this.INCIDENT_TRANSITIONS[inc.status] || [];
    openModal({
      title: `${inc.code} -- ${inc.status}`,
      bodyHtml: `
        <dl class="kv-list"><dt>Type</dt><dd>${esc(inc.type)}</dd><dt>Severity</dt><dd>${statusBadge(inc.severity)}</dd><dt>Description</dt><dd>${esc(inc.description || "")}</dd></dl>
        ${legal.length ? `<div class="section-divider">Transition</div>
        <div style="display:flex;gap:8px;flex-wrap:wrap">
          <select id="inc-select">${legal.map((s) => `<option value="${s}">${s}</option>`).join("")}</select>
          <input id="inc-reason" placeholder="reason (required for CLOSED)" style="flex:1;min-width:160px;padding:6px;border:1px solid var(--border);border-radius:6px" />
          <button class="btn btn-primary btn-sm" id="inc-apply">Apply</button>
        </div>` : ""}
      `,
      footerHtml: `<button class="btn" id="close-btn">Close</button>`,
      onMount: () => {
        document.getElementById("close-btn").onclick = closeModal;
        const apply = document.getElementById("inc-apply");
        if (apply) apply.onclick = async () => {
          const toState = document.getElementById("inc-select").value;
          const reason = document.getElementById("inc-reason").value;
          try { await Api.post(`/v1/incidents/${id}/transitions`, { toState, reason }); toast(`Incident -> ${toState}.`, "success"); closeModal(); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Overrides (Section 27) ----------------

  async overrides() {
    const d = await Api.get("/v1/overrides");
    const canRequest = Auth.hasPerm("CREATE_OVERRIDE");
    const canApprove = Auth.hasPerm("APPROVE_OVERRIDE");
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Overrides</h2><div class="page-actions">${canRequest ? `<button class="btn btn-primary" id="new-override-btn">+ Request Override</button>` : ""}</div></div>
      <p class="flow-note">Every override is a first-class, audited record linked to its own AuditLog entry (Section 27) -- never a silently bypassed check.</p>
      <div class="card">${dataTable([
        { label: "Conflict Type", key: "conflictType" }, { label: "Entity", render: (o) => `${o.entityType} / ${(o.entityId || "").slice(0, 8)}` },
        { label: "Reason", key: "reason" }, { label: "Status", render: (o) => statusBadge(o.status) }, { label: "Requested", render: (o) => fmtDate(o.timestamp) },
        { label: "", render: (o) => canApprove && o.status === "PENDING" ? `<button class="btn btn-sm" data-approve="${o.id}">Approve</button> <button class="btn btn-sm" data-reject="${o.id}">Reject</button>` : "" },
      ], d.items, { emptyText: "No overrides requested." })}</div>
    `;
    if (canRequest) document.getElementById("new-override-btn").addEventListener("click", () => this.newOverrideModal());
    if (canApprove) {
      content.querySelectorAll("[data-approve]").forEach((b) => b.addEventListener("click", async () => { try { await Api.post(`/v1/overrides/${b.dataset.approve}/approve`, { reason: prompt("Approval note?") || "" }); toast("Override approved.", "success"); App.route(); } catch (e) { notifyError(e); } }));
      content.querySelectorAll("[data-reject]").forEach((b) => b.addEventListener("click", async () => { try { await Api.post(`/v1/overrides/${b.dataset.reject}/reject`, { reason: prompt("Rejection reason?") || "" }); toast("Override rejected.", "success"); App.route(); } catch (e) { notifyError(e); } }));
    }
  },

  newOverrideModal() {
    openModal({
      title: "Request Override",
      bodyHtml: `<form id="ov-form"><div class="form-grid cols-1">
        <div class="field"><label>Conflict Type</label><input name="conflictType" placeholder="e.g. RESOURCE_CONFLICT" required /></div>
        <div class="field"><label>Entity Type</label><input name="entityType" placeholder="e.g. PRODUCTION_ORDER" required /></div>
        <div class="field"><label>Entity ID</label><input name="entityId" required /></div>
        <div class="field"><label>Reason</label><input name="reason" required /></div>
        <div class="field"><label>Justification</label><textarea name="justification" required></textarea></div>
      </div></form>`,
      footerHtml: `<button class="btn" id="cancel-btn">Cancel</button><button class="btn btn-primary" id="save-btn">Submit</button>`,
      onMount: () => {
        document.getElementById("cancel-btn").onclick = closeModal;
        document.getElementById("save-btn").onclick = async () => {
          try { await Api.post("/v1/overrides", formToObject(document.getElementById("ov-form"))); closeModal(); toast("Override requested.", "success"); App.route(); }
          catch (err) { notifyError(err); }
        };
      },
    });
  },

  // ---------------- Traceability Explorer (Section 37) ----------------

  async traceability() {
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="page-header"><h2>Traceability Explorer</h2></div>
      <div class="card">
        <h3>Find a record</h3>
        <p class="flow-note">Search by a familiar reference, such as <strong>PO-100</strong>, <strong>PR-201</strong>, <strong>PB-201</strong>, <strong>MB-001</strong>, or <strong>M-03</strong>. Then choose a result to see its history.</p>
        <form id="trace-search-form" class="trace-search-form">
          <input id="trace-query" placeholder="Search order, run, batch, machine, defect, or incident" autocomplete="off" />
          <button class="btn btn-primary" type="submit">Search</button>
        </form>
      </div>
      <div id="trace-search-results"></div>
      <div id="trace-output"></div>
    `;
    content.querySelector("#trace-search-form").addEventListener("submit", (event) => {
      event.preventDefault();
      void this.searchTrace(content.querySelector("#trace-query").value);
    });
  },

  async openTraceModal(type, id) {
    App.navigate("traceability");
    setTimeout(async () => {
      await this.runTrace(type, id);
    }, 60);
  },

  async searchTrace(query) {
    const results = document.getElementById("trace-search-results");
    const output = document.getElementById("trace-output");
    const q = query.trim();
    output.innerHTML = "";
    if (q.length < 2) {
      results.innerHTML = `<div class="empty-state">Enter at least two characters to search.</div>`;
      return;
    }
    results.innerHTML = `<div class="empty-state">Searching...</div>`;
    try {
      const d = await Api.get(`/v1/traceability/lookup?q=${encodeURIComponent(q)}`);
      if (!results.isConnected) return;
      results.innerHTML = d.items.length ? `<div class="card"><h3>Choose a matching record</h3>${dataTable([
        { label: "Reference", render: (item) => `<button class="link-btn" data-trace-type="${esc(item.entityType)}" data-trace-id="${esc(item.id)}">${esc(item.reference)}</button>` },
        { label: "Type", render: (item) => esc(item.entityType.replaceAll("_", " ")) },
        { label: "Description", key: "description" },
        { label: "Status", render: (item) => item.status ? statusBadge(item.status) : "-" },
      ], d.items, { emptyText: "No matching traceable records." })}</div>` : `<div class="empty-state">No matching traceable records. Try a code such as PO-100 or MB-001.</div>`;
      results.querySelectorAll("[data-trace-id]").forEach((button) => button.addEventListener("click", () => {
        void this.runTrace(button.dataset.traceType, button.dataset.traceId);
      }));
    } catch (err) {
      if (!results.isConnected) return;
      results.innerHTML = `<div class="empty-state"><strong>Search couldn’t be completed.</strong><br/>${esc(apiErrorMessage(err))}</div>`;
    }
  },

  async runTrace(type, id) {
    if (!id) return;
    const out = document.getElementById("trace-output");
    const results = document.getElementById("trace-search-results");
    out.innerHTML = `<div class="empty-state">Loading...</div>`;
    try {
      const d = await Api.get(`/v1/traceability/${type}/${id}`);
      if (!out.isConnected) return;
      if (results) results.innerHTML = "";
      out.innerHTML = `<div class="card">${this.renderTraceNode(d)}</div>`;
    } catch (err) {
      if (!out.isConnected) return;
      out.innerHTML = `<div class="empty-state">${esc(apiErrorMessage(err))}</div>`;
    }
  },

  renderRunNode(run) {
    return `
      <div class="trace-node">
        <strong>Run ${esc(run.runCode)}</strong> ${statusBadge(run.status)} on ${esc(run.machineName || "?")}
        ${run.materialBatches.length ? `<div style="margin-top:4px">${run.materialBatches.map((b) => `<span class="badge badge-blue" style="margin-right:4px">${esc(b.lotNumber)} (${esc(b.materialName)}): ${fmtNum(b.quantityReserved)} reserved${b.quantityConsumed !== null ? ", " + fmtNum(b.quantityConsumed) + " consumed" : ""}</span>`).join("")}</div>` : ""}
        ${run.productBatches.length ? `<div style="margin-top:4px">Output: ${run.productBatches.map((p) => `<span class="badge badge-primary" style="margin-right:4px">${esc(p.code)} (${fmtNum(p.quantityProduced)}) ${statusBadge(p.qualityDisposition)}</span>`).join("")}</div>` : ""}
      </div>`;
  },

  renderTraceNode(d) {
    if (d.entityType === "PRODUCTION_ORDER") {
      return `<h3>Order ${esc(d.order.code)} -- ${esc(d.order.productName)}</h3>${statusBadge(d.order.status)}
        <div class="section-divider">Runs</div>${d.runs.map((r) => this.renderRunNode(r)).join("") || "<p class='muted'>No runs.</p>"}`;
    }
    if (d.entityType === "PRODUCTION_RUN") {
      return `<h3>Run ${esc(d.run.runCode)}</h3>${this.renderRunNode(d.run)}
        <div class="section-divider">Inspections</div>${dataTable([{ label: "Code", key: "code" }, { label: "Result", render: (i) => statusBadge(i.result) }, { label: "Parameter", key: "parameter" }], d.run.inspections, { emptyText: "None." })}`;
    }
    if (d.entityType === "PRODUCT_BATCH") {
      return `<h3>Product Batch ${esc(d.productBatch.code)}</h3>${statusBadge(d.productBatch.qualityDisposition)}
        <p>Produced: ${fmtNum(d.productBatch.quantityProduced)} | Scrapped: ${fmtNum(d.productBatch.scrappedQuantity)}</p>
        ${d.run ? `<div class="section-divider">Genealogy</div>${this.renderRunNode(d.run)}` : ""}
        <div class="section-divider">Defects</div>${dataTable([{ label: "Code", key: "code" }, { label: "Severity", render: (x) => statusBadge(x.severity) }], d.defects, { emptyText: "None." })}`;
    }
    if (d.entityType === "MATERIAL_BATCH") {
      const b = d.materialBatch;
      return `<h3>Material Batch ${esc(b.lotNumber)}</h3>${statusBadge(b.status)}
        <p>Total: ${fmtNum(b.totalQuantity)} | Reserved: ${fmtNum(b.reservedQuantity)} | Consumed: ${fmtNum(b.consumedQuantity)} | Available: ${fmtNum(b.availableQuantity)}</p>
        <div class="section-divider">Forward Recall -- affected runs (Acceptance Test AT-4)</div>
        ${d.forwardRecall.affectedRuns.map((r) => this.renderRunNode(r)).join("") || "<p class='muted'>Not yet consumed by any run.</p>"}
        <p class="muted" style="margin-top:8px">Affected orders: ${d.forwardRecall.affectedOrderIds.length}</p>`;
    }
    if (d.entityType === "MACHINE") {
      return `<h3>Machine ${esc(d.machine.name)}</h3>${statusBadge(d.machine.status)}
        <div class="section-divider">Runs</div>${d.runs.map((r) => this.renderRunNode(r)).join("") || "<p class='muted'>No runs.</p>"}
        <div class="section-divider">Maintenance History</div>${dataTable([{ label: "Type", key: "type" }, { label: "Status", render: (m) => statusBadge(m.status) }, { label: "Opened", render: (m) => fmtDate(m.openedAt) }], d.maintenanceHistory, { emptyText: "None." })}`;
    }
    if (d.entityType === "OPERATOR") {
      return `<h3>Operator</h3><div class="section-divider">Runs</div>${d.runs.map((r) => this.renderRunNode(r)).join("") || "<p class='muted'>No runs.</p>"}`;
    }
    if (d.entityType === "DEFECT") {
      return `<h3>Defect ${esc(d.defect.code)}</h3>${statusBadge(d.defect.severity)} ${statusBadge(d.defect.status)}<p>${esc(d.defect.description || "")}</p>
        ${d.run ? `<div class="section-divider">Traced Run</div>${this.renderRunNode(d.run)}` : ""}`;
    }
    if (d.entityType === "INCIDENT") {
      return `<h3>Incident ${esc(d.incident.code)}</h3>${statusBadge(d.incident.severity)} ${statusBadge(d.incident.status)}<p>${esc(d.incident.description || "")}</p>
        ${d.run ? `<div class="section-divider">Traced Run</div>${this.renderRunNode(d.run)}` : ""}`;
    }
    return `<pre>${esc(JSON.stringify(d, null, 2))}</pre>`;
  },
};
window.Views = Views;
